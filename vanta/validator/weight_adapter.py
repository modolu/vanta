"""Reputation keyed by hotkey, weights submitted by uid (ARCHITECTURE.md §19-§21).

On chain a **uid is a slot, not an identity**. When a miner deregisters, its uid is
recycled to a different hotkey — a different operator, running different code. Carrying
reputation across that boundary would credit a newcomer with a departed miner's track
record, or punish it for one, and would corrupt both the weight vector and the §20
probation window.

So Vanta stores reputation under the hotkey and resolves the current uid from the
metagraph at submission time. A uid whose hotkey changed is treated as what it is: a new
miner, starting fresh and provisional.

This module changes no scoring rule. It selects *whose* reputation is submitted under
*which* uid, and defers every number to :func:`vanta.validator.weights.compute_weights`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from vanta.log import get_logger
from vanta.neurons.chain import NeuronRecord
from vanta.validator.reputation import DEFAULT_EMA_ALPHA, MinerReputation
from vanta.validator.weights import DEFAULT_GAMMA, compute_weights

__all__ = ["DEFAULT_PROVISIONAL_SCALE", "MinerRegistry", "WeightSubmission"]

logger = get_logger(__name__)

# §20: no probation penalty until simulation evidence justifies one.
DEFAULT_PROVISIONAL_SCALE = 1.0


@dataclass(frozen=True, slots=True)
class WeightSubmission:
    """A weight vector ready for the chain, and the identities behind it."""

    weights: dict[int, float]
    hotkeys: dict[int, str]
    provisional_uids: frozenset[int]

    def __bool__(self) -> bool:
        return bool(self.weights)


class MinerRegistry:
    """Reputation state for the miners this validator has scored, keyed by hotkey."""

    def __init__(
        self,
        *,
        alpha: float = DEFAULT_EMA_ALPHA,
        gamma: float = DEFAULT_GAMMA,
        provisional_scale: float = DEFAULT_PROVISIONAL_SCALE,
    ) -> None:
        self._alpha = alpha
        self._gamma = gamma
        self._provisional_scale = provisional_scale
        self._reputation: dict[str, MinerReputation] = {}
        # Last uid each hotkey occupied, used only to detect and log slot churn.
        self._last_uid: dict[str, int] = {}

    @property
    def tracked(self) -> int:
        return len(self._reputation)

    def hotkeys(self) -> frozenset[str]:
        return frozenset(self._reputation)

    def reputation_for(self, hotkey: str, uid: int) -> MinerReputation:
        """The reputation record for ``hotkey``, created fresh on first sight."""
        record = self._reputation.get(hotkey)
        if record is None:
            record = MinerReputation(miner_uid=uid, alpha=self._alpha)
            self._reputation[hotkey] = record
        self._last_uid[hotkey] = uid
        return record

    def record(
        self, hotkey: str, uid: int, *, total_score: float, probability_up: float, outcome: float
    ) -> None:
        """Fold one scored forecast into a miner's reputation.

        Delegates entirely to :meth:`MinerReputation.record` — the EMA, the calibration
        tracker and the probation window are unchanged from Phase 1.
        """
        self.reputation_for(hotkey, uid).record(total_score, probability_up, outcome)

    def sync(self, neurons: Sequence[NeuronRecord]) -> frozenset[str]:
        """Reconcile stored reputation against the current metagraph.

        Any hotkey no longer registered on the subnet is dropped: its reputation is not
        submittable (it has no uid), and keeping it would let it reappear if the hotkey
        ever re-registered into a different slot.

        Returns:
            The hotkeys that were dropped.
        """
        registered = {neuron.hotkey for neuron in neurons}
        departed = frozenset(self._reputation) - registered
        for hotkey in departed:
            self._reputation.pop(hotkey, None)
            previous = self._last_uid.pop(hotkey, None)
            logger.info(
                "dropping reputation for deregistered hotkey %s (was uid %s)", hotkey, previous
            )
        return departed

    def observe(self, neurons: Sequence[NeuronRecord]) -> None:
        """Note the uid each known hotkey currently occupies, logging any churn.

        A uid whose occupant changed needs no special handling here — the newcomer's
        hotkey simply has no reputation record yet, so it starts fresh and provisional.
        This exists to make that transition visible in the logs.
        """
        by_uid = {neuron.uid: neuron.hotkey for neuron in neurons}
        for hotkey, uid in list(self._last_uid.items()):
            current = by_uid.get(uid)
            if current is not None and current != hotkey:
                logger.info(
                    "uid %d changed hands: %s -> %s; the new hotkey starts provisional",
                    uid,
                    hotkey,
                    current,
                )

    def submission(self, neurons: Sequence[NeuronRecord]) -> WeightSubmission:
        """Build the weight vector for the subnet's *current* uid assignment.

        Only registered hotkeys with a reputation record are weighted. A registered
        miner this validator has never scored contributes nothing rather than a
        default score, because inventing a score for an unobserved miner would be a
        mechanism rule that §19-§21 do not define.
        """
        self.observe(neurons)
        scores: dict[int, float] = {}
        hotkeys: dict[int, str] = {}
        provisional: set[int] = set()

        for neuron in neurons:
            record = self._reputation.get(neuron.hotkey)
            if record is None:
                continue
            scores[neuron.uid] = record.score
            hotkeys[neuron.uid] = neuron.hotkey
            if record.is_provisional:
                provisional.add(neuron.uid)

        if not scores:
            return WeightSubmission(weights={}, hotkeys={}, provisional_uids=frozenset())

        weights = compute_weights(
            scores,
            gamma=self._gamma,
            provisional=provisional,
            provisional_scale=self._provisional_scale,
        )
        return WeightSubmission(
            weights=weights, hotkeys=hotkeys, provisional_uids=frozenset(provisional)
        )

    def snapshot(self) -> Mapping[str, float]:
        """Current reputation score per hotkey. For logging and the leaderboard."""
        return {hotkey: record.score for hotkey, record in self._reputation.items()}
