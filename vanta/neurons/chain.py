"""The only module that talks to the Bittensor SDK.

Everything the neurons need from the chain — reading the metagraph, publishing an axon
endpoint, signing and verifying HTTP requests, submitting weights — is behind the
protocols in this module. The rest of Vanta depends on those protocols, never on
``bittensor``, which is what keeps the mechanism testable (and installable) without the
chain SDK.

The SDK import is deliberately lazy: importing this module is free, and only
:func:`connect` and :func:`load_wallet` pull ``bittensor`` in.

bittensor 11 API used here
--------------------------
``bittensor.Wallet(name, hotkey)``           wallet handle; ``.hotkey.ss58_address``
``bittensor.Subtensor(network)``             blocking chain client (lazily connected)
``client.subnets.metagraph(netuid)``         typed ``Metagraph`` of ``MetagraphNeuron``
``bittensor.ServeAxon(...)`` + ``execute``   publish ip:port on chain
``bittensor.set_weights(netuid, {uid: w})``  conform + submit; raises on failure
``bittensor.http_auth.sign`` / ``.verify``   the btauth/1 signed-request protocol

v11 has no axon/dendrite/synapse networking stack; the HTTP layer is ours (see
:mod:`vanta.protocol.synapse`) and only its *identity* comes from the SDK.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from vanta.log import get_logger

__all__ = [
    "BittensorChain",
    "ChainError",
    "MinerEndpoint",
    "NeuronRecord",
    "RequestSigner",
    "RequestVerifier",
    "SubnetView",
    "WeightSubmitter",
    "connect",
    "hotkey_address",
    "load_wallet",
    "make_signer",
    "make_verifier",
]

logger = get_logger(__name__)


class ChainError(RuntimeError):
    """A chain interaction failed. Wraps the SDK's own errors so callers need not
    import ``bittensor`` to handle them."""


@dataclass(frozen=True, slots=True)
class NeuronRecord:
    """One neuron as Vanta needs it: identity, endpoint, and stake.

    A flattened projection of ``bittensor.MetagraphNeuron``. Vanta keys reputation by
    ``hotkey``, never by ``uid`` — a uid is a recyclable slot, and a deregistration
    hands the same uid to a different operator.
    """

    uid: int
    hotkey: str
    axon: str | None
    validator_permit: bool
    # Total stake in the subnet's own units (alpha), not TAO. A subnet stake Balance
    # refuses to be read as TAO at all, so naming this "tao" would be a lie that the
    # SDK itself rejects.
    stake: float

    @property
    def is_servable(self) -> bool:
        """Whether this neuron published an endpoint a validator can query."""
        return bool(self.axon)


@dataclass(frozen=True, slots=True)
class MinerEndpoint:
    """A queryable miner: where to reach it, and whose signature to expect."""

    uid: int
    hotkey: str
    url: str


class SubnetView(Protocol):
    """Read side of the chain."""

    def neurons(self, netuid: int) -> list[NeuronRecord]:
        """Every registered neuron on the subnet, ordered by uid."""


class WeightSubmitter(Protocol):
    """Write side of the chain."""

    def set_weights(self, netuid: int, weights: Mapping[int, float]) -> str:
        """Submit a ``{uid: weight}`` vector. Returns a short result description.

        Raises:
            ChainError: if the submission failed.
        """


class RequestSigner(Protocol):
    """Produces btauth/1 headers authenticating an outbound request."""

    def __call__(
        self, *, method: str, path: str, body: bytes, receiver_ss58: str
    ) -> dict[str, str]: ...


class RequestVerifier(Protocol):
    """Authenticates an inbound request, returning the caller's hotkey.

    Raises:
        ChainError: if the request is unauthenticated, stale, replayed or misaddressed.
    """

    def __call__(
        self, *, headers: Mapping[str, str], body: bytes, method: str, path: str
    ) -> str: ...


# --- SDK-backed implementations ---------------------------------------------------


def _bittensor() -> Any:
    """Import the SDK on demand, with an actionable message when it is absent."""
    try:
        import bittensor
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ChainError(
            "the Bittensor SDK is not installed; run `pip install -e '.[chain]'` to use "
            "the chain layer (the mechanism and simulation do not need it)"
        ) from exc
    return bittensor


def load_wallet(name: str, hotkey: str) -> Any:
    """Open a wallet by name from the operator's ``~/.bittensor/wallets``.

    Only the hotkey is ever used at runtime: it serves the axon, signs requests and
    signs the weight extrinsic. The coldkey is never unlocked here, and no key material
    is read from configuration or from this repository (§45).
    """
    bt = _bittensor()
    try:
        return bt.Wallet(name=name, hotkey=hotkey)
    except Exception as exc:
        raise ChainError(f"could not open wallet {name!r}/{hotkey!r}: {exc}") from exc


def hotkey_address(wallet: Any) -> str:
    """The ss58 address of a wallet's hotkey."""
    try:
        return str(wallet.hotkey.ss58_address)
    except Exception as exc:
        raise ChainError(f"could not read the hotkey address: {exc}") from exc


def _describe(result: Any) -> str:
    """A one-line summary of an extrinsic result.

    ``str(result)`` renders the full decoded event list, which is unreadable in a log
    line; the identifying fields are what an operator actually needs to chase a
    submission on chain.
    """
    events = [event.get("event_id") for event in (getattr(result, "events", None) or [])]
    return (
        f"success={getattr(result, 'success', None)} "
        f"block={getattr(result, 'block_hash', None)} "
        f"extrinsic={getattr(result, 'extrinsic_id', None)} "
        f"events={events}"
    )


def _balance_amount(balance: Any) -> float:
    """Numeric magnitude of a Balance, whatever unit it is denominated in.

    Subnet stakes are alpha and root stakes are TAO; ``Balance.tao`` raises outright on
    an alpha balance, so the unit-agnostic ``amount`` is the only safe accessor here.
    """
    try:
        return float(balance.amount)
    except Exception:
        try:
            return float(balance.rao) / 1e9
        except Exception:
            return 0.0


class BittensorChain:
    """Concrete :class:`SubnetView` + :class:`WeightSubmitter` over one network."""

    def __init__(self, network: str, wallet: Any) -> None:
        bt = _bittensor()
        self._bt = bt
        self._network = network
        self._wallet = wallet
        self._client = bt.Subtensor(network)

    @property
    def network(self) -> str:
        return self._network

    def neurons(self, netuid: int) -> list[NeuronRecord]:
        try:
            metagraph = self._client.subnets.metagraph(netuid, commitments=False)
        except Exception as exc:
            raise ChainError(f"could not read the metagraph for netuid {netuid}: {exc}") from exc
        if metagraph is None:
            raise ChainError(f"netuid {netuid} does not exist on {self._network}")
        return [
            NeuronRecord(
                uid=int(neuron.uid),
                hotkey=str(neuron.hotkey),
                axon=neuron.axon,
                validator_permit=bool(neuron.validator_permit),
                stake=_balance_amount(neuron.total_stake),
            )
            for neuron in metagraph.neurons
        ]

    def serve_axon(self, netuid: int, ip: str, port: int) -> str:
        """Publish this hotkey's endpoint on chain (the ServeAxon intent).

        This writes connection info only — it starts no server. The HTTP service is
        ours to run.
        """
        intent = self._bt.ServeAxon(netuid=netuid, ip=ip, port=port)
        try:
            # execute() returns a result rather than raising: an extrinsic that the
            # chain rejected comes back with success=False, so it must be checked or
            # the caller believes it published an endpoint it did not.
            result = self._client.execute(intent, self._wallet).raise_for_failure()
        except Exception as exc:
            raise ChainError(f"serve_axon {ip}:{port} on netuid {netuid} failed: {exc}") from exc
        return str(result)

    def set_weights(self, netuid: int, weights: Mapping[int, float]) -> str:
        """Submit the weight vector.

        The SDK conforms the vector to the subnet's hyperparameters (max-weight clip,
        u16 quantization, minimum weight count), picks the plaintext or commit-reveal
        path, preflights registration and the rate limit, and raises on failure — so
        Vanta submits proportions and does no chain-side arithmetic of its own.
        """
        if not weights:
            raise ChainError("refusing to submit an empty weight vector")
        try:
            result = self._bt.set_weights(
                netuid,
                dict(weights),
                wallet=self._wallet,
                network=self._network,
            )
        except Exception as exc:
            raise ChainError(f"set_weights on netuid {netuid} failed: {exc}") from exc
        return _describe(result)


def connect(network: str, wallet: Any) -> BittensorChain:
    """Build a chain client. Construction is cold; no socket opens until first use."""
    return BittensorChain(network, wallet)


def make_signer(wallet: Any) -> RequestSigner:
    """A :class:`RequestSigner` backed by ``bittensor.http_auth.sign``."""
    bt = _bittensor()

    def sign(*, method: str, path: str, body: bytes, receiver_ss58: str) -> dict[str, str]:
        # Every call signs a fresh nonce; a retry must re-sign, never reuse headers,
        # or the receiver rejects it as a replay.
        return bt.http_auth.sign(
            wallet, method=method, path=path, body=body, receiver_ss58=receiver_ss58
        )

    return sign


def make_verifier(self_hotkey_ss58: str) -> RequestVerifier:
    """A :class:`RequestVerifier` backed by ``bittensor.http_auth.verify``.

    Checks header shape, receiver binding, freshness, signature and replay. The body is
    hashed as received, before any parsing, so the signature covers exactly the bytes
    that arrived.
    """
    bt = _bittensor()
    nonce_store = bt.http_auth.InMemoryNonceStore()

    def verify(*, headers: Mapping[str, str], body: bytes, method: str, path: str) -> str:
        try:
            caller = bt.http_auth.verify(
                headers,
                body,
                method=method,
                path=path,
                self_hotkey_ss58=self_hotkey_ss58,
                nonce_store=nonce_store,
            )
        except bt.http_auth.AuthError as exc:
            raise ChainError(str(exc)) from exc
        return str(caller.hotkey_ss58)

    return verify
