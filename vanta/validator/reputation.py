"""Rolling miner reputation: EMA score, calibration and cold-start probation.

ARCHITECTURE.md §18 (calibration), §19 (EMA reputation), §20 (cold start).

This is the only stateful part of the mechanism. State is per-miner and updated in
task-resolution order, so replaying the same ordered stream reproduces it exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vanta.validation import (
    VantaValidationError,
    require_probability,
)

__all__ = [
    "DEFAULT_CALIBRATION_BINS",
    "DEFAULT_EMA_ALPHA",
    "NEUTRAL_CALIBRATION",
    "PROBATION_FORECASTS",
    "CalibrationTracker",
    "MinerReputation",
]

# §19: "For example, alpha = 0.1".
DEFAULT_EMA_ALPHA = 0.1

# §20: "First 10 forecasts: provisional score".
PROBATION_FORECASTS = 10

# §18 describes calibration qualitatively but gives no equation; we use the standard
# expected-calibration-error formulation over equal-width probability bins. Ten bins is
# the conventional default and makes the §18 worked example ("say 70% UP 100 times")
# land in its own bin.
DEFAULT_CALIBRATION_BINS = 10

# A miner with no resolved history has no measurable calibration. Scoring it as either
# perfectly or terribly calibrated would be a fabricated claim, so it scores neutral
# until evidence exists.
NEUTRAL_CALIBRATION = 0.5


class CalibrationTracker:
    """Rolling reliability of a miner's stated probabilities (§18).

    Accumulates ``(probability, outcome)`` pairs into equal-width bins and reports
    ``1 - ECE``, where ECE is the sample-weighted mean gap between the average stated
    probability in a bin and the realized frequency in that bin.
    """

    __slots__ = ("_bins", "_counts", "_outcome_sums", "_probability_sums")

    def __init__(self, bins: int = DEFAULT_CALIBRATION_BINS) -> None:
        if isinstance(bins, bool) or not isinstance(bins, int) or bins < 1:
            raise VantaValidationError(f"bins must be an int >= 1, got {bins!r}")
        self._bins = bins
        self._counts = [0] * bins
        self._probability_sums = [0.0] * bins
        self._outcome_sums = [0.0] * bins

    def record(self, probability_up: float, outcome: float) -> None:
        """Add one resolved forecast to the calibration history."""
        probability = require_probability(probability_up, "probability_up")
        y = require_probability(outcome, "outcome")
        index = min(int(probability * self._bins), self._bins - 1)
        self._counts[index] += 1
        self._probability_sums[index] += probability
        self._outcome_sums[index] += y

    @property
    def sample_count(self) -> int:
        return sum(self._counts)

    @property
    def expected_calibration_error(self) -> float:
        """Sample-weighted mean |stated probability - realized frequency|, in [0, 1]."""
        total = self.sample_count
        if total == 0:
            return 0.0
        error = 0.0
        for count, probability_sum, outcome_sum in zip(
            self._counts, self._probability_sums, self._outcome_sums, strict=True
        ):
            if count == 0:
                continue
            error += count * abs((probability_sum / count) - (outcome_sum / count))
        return error / total

    @property
    def quality(self) -> float:
        """Calibration as a 0-1 quality: ``1 - ECE``, or neutral with no history."""
        if self.sample_count == 0:
            return NEUTRAL_CALIBRATION
        return 1.0 - self.expected_calibration_error


@dataclass(slots=True)
class MinerReputation:
    """Historical state for one miner (§19), the input to weighting and consensus."""

    miner_uid: int
    alpha: float = DEFAULT_EMA_ALPHA
    ema_score: float | None = None
    forecast_count: int = 0
    calibration: CalibrationTracker = field(default_factory=CalibrationTracker)

    def __post_init__(self) -> None:
        if isinstance(self.miner_uid, bool) or not isinstance(self.miner_uid, int):
            raise VantaValidationError(f"miner_uid must be an int, got {self.miner_uid!r}")
        if self.miner_uid < 0:
            raise VantaValidationError(f"miner_uid must be >= 0, got {self.miner_uid!r}")
        alpha = require_probability(self.alpha, "alpha")
        if alpha <= 0.0:
            raise VantaValidationError(f"alpha must lie in (0, 1], got {alpha!r}")
        self.alpha = alpha
        if self.ema_score is not None:
            self.ema_score = require_probability(self.ema_score, "ema_score")
        if self.forecast_count < 0:
            raise VantaValidationError(f"forecast_count must be >= 0, got {self.forecast_count!r}")

    @property
    def calibration_component(self) -> float:
        """Calibration term to feed into the next forecast's Vanta Score (§15, §18)."""
        return self.calibration.quality

    @property
    def score(self) -> float:
        """Reputation as a plain number; a miner with no history contributes nothing."""
        return 0.0 if self.ema_score is None else self.ema_score

    @property
    def is_provisional(self) -> bool:
        """True while the miner is inside its §20 probation window."""
        return self.forecast_count < PROBATION_FORECASTS

    def record(self, total_score: float, probability_up: float, outcome: float) -> None:
        """Fold one resolved forecast into this miner's reputation.

        The EMA follows §19: ``R_t = alpha * score + (1 - alpha) * R_(t-1)``. The first
        observation seeds ``R_0`` directly rather than decaying from an invented prior.
        """
        score = require_probability(total_score, "total_score")
        self.calibration.record(probability_up, outcome)
        self.ema_score = (
            score
            if self.ema_score is None
            else self.alpha * score + (1.0 - self.alpha) * self.ema_score
        )
        self.forecast_count += 1
