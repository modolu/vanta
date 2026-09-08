"""Reputation -> normalized validator weight vector (ARCHITECTURE.md §21, §22).

    weight_i  proportional to  score_i ** gamma,   normalized so the vector sums to 1.

Gamma above 1 emphasizes quality differences without collapsing into winner-take-all,
which §22 rejects as producing unstable incentives.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from vanta.validation import (
    VantaValidationError,
    require_non_negative,
    require_positive,
)

__all__ = ["DEFAULT_GAMMA", "compute_weights"]

# §21 states only "gamma > 1". 1.2 is the value that most closely reproduces the worked
# example in that section (scores .81/.72/.54/.31/.15 -> roughly 35/28/20/11/6 percent).
DEFAULT_GAMMA = 1.2


def compute_weights(
    scores: Mapping[int, float],
    *,
    gamma: float = DEFAULT_GAMMA,
    provisional: Collection[int] | None = None,
    provisional_scale: float = 1.0,
) -> dict[int, float]:
    """Convert miner reputation scores into a normalized weight vector.

    Args:
        scores: miner UID -> reputation score, each finite and non-negative.
        gamma: emphasis exponent. §21 recommends > 1.
        provisional: UIDs still inside the §20 probation window.
        provisional_scale: multiplier applied to provisional miners' weights before
            normalization. Defaults to 1.0 (no penalty) because §20 requires new miners
            to receive "limited weight" but never quantifies it; set it explicitly once
            that factor is decided.

    Returns:
        UID -> weight, summing to 1.0.

    Raises:
        VantaValidationError: on an empty mapping, or any invalid score or parameter.
    """
    if not scores:
        raise VantaValidationError("cannot compute weights from an empty score mapping")

    exponent = require_positive(gamma, "gamma")
    scale = require_non_negative(provisional_scale, "provisional_scale")
    probationers = set() if provisional is None else set(provisional)

    raw: dict[int, float] = {}
    for uid, score in scores.items():
        if isinstance(uid, bool) or not isinstance(uid, int) or uid < 0:
            raise VantaValidationError(f"miner uid must be an int >= 0, got {uid!r}")
        value = require_non_negative(score, f"score for miner {uid}")
        weight = value**exponent
        if uid in probationers:
            weight *= scale
        raw[uid] = weight

    total = sum(raw.values())
    if total <= 0.0:
        # Every miner scored zero (or every non-zero miner was scaled to zero). There is
        # no basis to prefer any of them, so weight is spread evenly rather than raising
        # and leaving the validator with no vector to submit.
        uniform = 1.0 / len(raw)
        return dict.fromkeys(raw, uniform)

    return {uid: weight / total for uid, weight in raw.items()}
