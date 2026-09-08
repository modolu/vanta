"""Reliability-weighted network consensus (ARCHITECTURE.md §30).

    P_consensus = sum(w_i * p_i) / sum(w_i)

where ``w_i`` is the miner's reliability (its reputation score). Dispersion is reported
as a raw statistic because §31 lists it as an input to network confidence; the
confidence score itself is deliberately not implemented, since §31 names its ingredients
but not its equation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from vanta.validation import (
    VantaValidationError,
    require_non_negative,
    require_probability,
)

__all__ = ["ConsensusResult", "consensus_probability"]


@dataclass(frozen=True, slots=True)
class ConsensusResult:
    """The network's aggregate view of one task."""

    probability_up: float
    dispersion: float
    contributing_miners: int
    total_weight: float


def consensus_probability(
    probabilities: Mapping[int, float],
    reliabilities: Mapping[int, float],
) -> ConsensusResult:
    """Aggregate miner probabilities weighted by reliability.

    Args:
        probabilities: miner UID -> stated probability that the market rises.
        reliabilities: miner UID -> non-negative reliability weight. Must cover every
            UID present in ``probabilities``; a missing entry is an error rather than a
            silent exclusion, so a miner is never dropped from consensus unnoticed.

    Returns:
        The weighted consensus probability, the reliability-weighted standard deviation
        of the miner probabilities, the number of contributing miners, and the total
        reliability behind the result.

    Raises:
        VantaValidationError: on empty input, a missing reliability, or an invalid value.
    """
    if not probabilities:
        raise VantaValidationError("cannot compute consensus from zero forecasts")

    weighted: dict[int, tuple[float, float]] = {}
    for uid, probability in probabilities.items():
        if isinstance(uid, bool) or not isinstance(uid, int) or uid < 0:
            raise VantaValidationError(f"miner uid must be an int >= 0, got {uid!r}")
        if uid not in reliabilities:
            raise VantaValidationError(f"no reliability supplied for miner {uid}")
        weighted[uid] = (
            require_probability(probability, f"probability_up for miner {uid}"),
            require_non_negative(reliabilities[uid], f"reliability for miner {uid}"),
        )

    total_weight = sum(weight for _, weight in weighted.values())
    if total_weight <= 0.0:
        # No miner carries any reliability yet, so none can be preferred over another;
        # fall back to an equal-weighted mean rather than reporting a divide-by-zero.
        effective = {uid: (probability, 1.0) for uid, (probability, _) in weighted.items()}
        effective_total = float(len(effective))
    else:
        effective = weighted
        effective_total = total_weight

    mean = sum(probability * weight for probability, weight in effective.values()) / effective_total
    variance = (
        sum(weight * (probability - mean) ** 2 for probability, weight in effective.values())
        / effective_total
    )

    return ConsensusResult(
        probability_up=mean,
        dispersion=math.sqrt(max(variance, 0.0)),
        contributing_miners=len(weighted),
        total_weight=total_weight,
    )
