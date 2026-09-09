"""Querying miners and collecting their forecasts (ARCHITECTURE.md §7, §27).

bittensor v11 has no dendrite, so the fan-out is a plain concurrent HTTP POST to each
miner's published endpoint, authenticated with the btauth/1 headers the validator's
hotkey produces. Neither the signer nor the transport is imported here directly: both
arrive as protocols, so this module — and everything downstream of it — stays testable
without the chain SDK or a network.

Two mechanism rules are enforced at this boundary:

* **§27 late-response gaming.** A response that arrives after the task deadline is
  discarded. A miner cannot wait for extra market movement and still be scored.
* **§29 response integrity.** Every payload is parsed through
  :func:`vanta.protocol.synapse.parse_response`, which rejects malformed fields and any
  response that answers a different task than the one asked.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from vanta.log import get_logger
from vanta.protocol.forecast import Forecast, ForecastTask
from vanta.protocol.synapse import FORECAST_PATH, parse_response, task_to_request
from vanta.validation import VantaValidationError

__all__ = [
    "CollectionResult",
    "ForecastCollector",
    "HttpxTransport",
    "MinerQuery",
    "Transport",
    "TransportReply",
]

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MinerQuery:
    """One miner to ask: its uid this round, its hotkey, and its endpoint."""

    uid: int
    hotkey: str
    url: str


@dataclass(frozen=True, slots=True)
class TransportReply:
    """What came back from one miner.

    Exactly one of ``payload`` / ``error`` is set. ``received_at`` is when the reply
    landed, which is what the §27 deadline check uses.
    """

    uid: int
    received_at: float
    payload: object | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.payload is not None


class Transport(Protocol):
    """Concurrent request fan-out. Never raises for an individual miner's failure —
    a failed call comes back as a :class:`TransportReply` carrying ``error``."""

    def post_all(
        self,
        calls: Sequence[tuple[MinerQuery, str, bytes, Mapping[str, str]]],
        *,
        timeout: float,
    ) -> list[TransportReply]:
        """Post to every miner concurrently and return one reply each."""


@dataclass(slots=True)
class CollectionResult:
    """Forecasts gathered for one task, plus why the rest were not counted."""

    task_id: str
    forecasts: dict[int, Forecast] = field(default_factory=dict)
    hotkeys: dict[int, str] = field(default_factory=dict)
    rejected: dict[int, str] = field(default_factory=dict)

    @property
    def responded(self) -> int:
        return len(self.forecasts)

    def __len__(self) -> int:
        return len(self.forecasts)


class ForecastCollector:
    """Fans a task out to miners and returns the forecasts that count."""

    def __init__(
        self,
        transport: Transport,
        *,
        signer: Callable[..., dict[str, str]] | None = None,
        timeout_seconds: float = 10.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        self._transport = transport
        self._signer = signer
        self._timeout = timeout_seconds
        self._clock = clock

    def collect(self, task: ForecastTask, miners: Sequence[MinerQuery]) -> CollectionResult:
        """Query ``miners`` for ``task`` and return the valid, on-time forecasts."""
        result = CollectionResult(task_id=task.task_id)
        if not miners:
            return result

        body = task_to_request(task).model_dump_json().encode("utf-8")
        calls: list[tuple[MinerQuery, str, bytes, Mapping[str, str]]] = []
        for miner in miners:
            result.hotkeys[miner.uid] = miner.hotkey
            try:
                headers = self._headers(miner, body)
            except Exception as exc:
                # A signing failure is ours, not the miner's, but the miner still cannot
                # be scored this round.
                result.rejected[miner.uid] = f"could not sign request: {exc}"
                continue
            calls.append((miner, f"{miner.url}{FORECAST_PATH}", body, headers))

        # Never outlive the submission window: a reply that lands after the deadline is
        # discarded anyway, so waiting past it only delays the round.
        budget = min(self._timeout, max(0.0, task.deadline - self._clock()))
        if budget <= 0.0:
            for miner, *_ in calls:
                result.rejected[miner.uid] = "deadline had already passed before querying"
            return result

        replies = self._transport.post_all(calls, timeout=budget)
        for reply in replies:
            self._absorb(task, reply, result)
        return result

    def _headers(self, miner: MinerQuery, body: bytes) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self._signer is not None:
            headers.update(
                self._signer(
                    method="POST",
                    path=FORECAST_PATH,
                    body=body,
                    receiver_ss58=miner.hotkey,
                )
            )
        return headers

    def _absorb(self, task: ForecastTask, reply: TransportReply, result: CollectionResult) -> None:
        if not reply.ok:
            result.rejected[reply.uid] = reply.error or "no response"
            return
        # §27: the hard deadline is the defense against waiting for more market
        # movement. Enforced on arrival time, before the payload is even trusted.
        if reply.received_at > task.deadline:
            result.rejected[reply.uid] = (
                f"late: arrived {reply.received_at - task.deadline:.2f}s after the deadline"
            )
            return
        try:
            forecast = parse_response(reply.payload, task_id=task.task_id, miner_uid=reply.uid)
        except VantaValidationError as exc:
            result.rejected[reply.uid] = str(exc)
            return
        result.forecasts[reply.uid] = forecast


class HttpxTransport:
    """Default :class:`Transport`: concurrent POSTs over httpx.

    ``httpx`` is imported on first use so the chain extra is only required by processes
    that actually talk to miners.
    """

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._httpx: Any | None = None
        # Reply timestamps must come from the same clock the collector compares them
        # against, or the deadline check is meaningless under a simulated clock.
        self._clock = clock

    def _client_module(self) -> Any:
        if self._httpx is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover - only without the chain extra
                raise RuntimeError(
                    "httpx is required to query miners; run `pip install -e '.[chain]'`"
                ) from exc
            self._httpx = httpx
        return self._httpx

    def post_all(
        self,
        calls: Sequence[tuple[MinerQuery, str, bytes, Mapping[str, str]]],
        *,
        timeout: float,
    ) -> list[TransportReply]:
        import asyncio

        if not calls:
            return []
        return asyncio.run(self._post_all(calls, timeout))

    async def _post_all(
        self,
        calls: Sequence[tuple[MinerQuery, str, bytes, Mapping[str, str]]],
        timeout: float,
    ) -> list[TransportReply]:
        httpx = self._client_module()
        import asyncio

        async with httpx.AsyncClient(timeout=timeout) as client:

            async def one(
                miner: MinerQuery, url: str, body: bytes, headers: Mapping[str, str]
            ) -> TransportReply:
                try:
                    response = await client.post(url, content=body, headers=dict(headers))
                    response.raise_for_status()
                    payload = response.json()
                except Exception as exc:
                    return TransportReply(
                        uid=miner.uid,
                        received_at=self._clock(),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                return TransportReply(uid=miner.uid, received_at=self._clock(), payload=payload)

            return list(await asyncio.gather(*(one(*call) for call in calls)))
