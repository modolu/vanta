"""The Vanta scoring engine (ARCHITECTURE.md §15-§17).

Every function here is pure: identical inputs always yield identical outputs, with no
clock, no I/O and no hidden state. That is what lets independent honest validators
agree on the same resolved task universe (§24).

    Vanta Score = 0.60 * probability quality
                + 0.30 * return score
                + 0.10 * calibration component

The calibration component is a *rolling*, history-based metric (§18) supplied by the
caller from the miner's prior reputation; it is not computed from a single forecast.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from vanta.protocol.forecast import Forecast, Resolution
from vanta.validation import (
    VantaValidationError,
    require_finite,
    require_positive,
    require_probability,
)

__all__ = [
    "CALIBRATION_WEIGHT",
    "PROBABILITY_WEIGHT",
    "RETURN_WEIGHT",
    "ForecastScore",
    "brier_score",
    "probability_quality",
    "return_score",
    "score_forecast",
    "vanta_score",
]

# §15. These must sum to 1.0.
PROBABILITY_WEIGHT = 0.60
RETURN_WEIGHT = 0.30
CALIBRATION_WEIGHT = 0.10


def brier_score(probability_up: float, outcome: float) -> float:
    """``(p - y)^2`` — lower is better (§16)."""
    probability = require_probability(probability_up, "probability_up")
    y = require_probability(outcome, "outcome")
    return (probability - y) ** 2


def probability_quality(probability_up: float, outcome: float) -> float:
    """``1 - (p - y)^2`` — the Brier score inverted into a 0-1 quality (§16)."""
    return 1.0 - brier_score(probability_up, outcome)


def return_score(predicted_return: float, actual_return: float, scale: float) -> float:
    """``exp(-|predicted - actual| / scale)`` (§17).

    ``scale`` normalizes the absolute error by normal market volatility for the horizon,
    giving a smooth 0-1 score. It is a required argument: the architecture defines the
    shape of this function but not the value of ``scale``, so the caller must supply a
    measured one rather than inherit an invented default.
    """
    predicted = require_finite(predicted_return, "predicted_return")
    actual = require_finite(actual_return, "actual_return")
    normalizer = require_positive(scale, "scale")
    return math.exp(-abs(predicted - actual) / normalizer)


def vanta_score(
    probability_quality_value: float,
    return_score_value: float,
    calibration_component: float,
) -> float:
    """Blend the three components into the Vanta Score (§15)."""
    probability = require_probability(probability_quality_value, "probability_quality_value")
    returns = require_probability(return_score_value, "return_score_value")
    calibration = require_probability(calibration_component, "calibration_component")
    return (
        PROBABILITY_WEIGHT * probability
        + RETURN_WEIGHT * returns
        + CALIBRATION_WEIGHT * calibration
    )


@dataclass(frozen=True, slots=True)
class ForecastScore:
    """Per-forecast scoring breakdown, mirroring the ``scores`` table in §37."""

    task_id: str
    miner_uid: int
    brier: float
    probability_quality: float
    return_score: float
    calibration_component: float
    total_score: float


def score_forecast(
    forecast: Forecast,
    resolution: Resolution,
    *,
    return_scale: float,
    calibration_component: float,
) -> ForecastScore:
    """Score one forecast against ground truth.

    ``calibration_component`` comes from the miner's reputation *before* this forecast,
    keeping the score causal — a forecast never contributes to its own calibration term.

    Raises:
        VoidResolutionError: if the market closed exactly flat (§14). Callers must skip
            void tasks; they contribute to neither scores nor calibration.
    """
    if forecast.task_id != resolution.task_id:
        raise VantaValidationError(
            f"forecast task_id {forecast.task_id!r} does not match "
            f"resolution task_id {resolution.task_id!r}"
        )

    outcome = resolution.require_outcome()
    brier = brier_score(forecast.probability_up, outcome)
    quality = 1.0 - brier
    returns = return_score(forecast.expected_return, resolution.realized_return, return_scale)
    calibration = require_probability(calibration_component, "calibration_component")

    return ForecastScore(
        task_id=forecast.task_id,
        miner_uid=forecast.miner_uid,
        brier=brier,
        probability_quality=quality,
        return_score=returns,
        calibration_component=calibration,
        total_score=vanta_score(quality, returns, calibration),
    )
