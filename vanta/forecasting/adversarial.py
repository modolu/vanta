"""Adversarial engine — the deliberately bad miner (ARCHITECTURE.md §25, §42).

Exercises two of the attacks the mechanism is meant to defeat at once: it always predicts
the same direction (attack 2) and always does so with extreme certainty (attack 3). It
exists to be punished. If a miner claiming 99% confidence and being wrong half the time
does not sink to the bottom of the leaderboard, the scoring is broken.
"""

from __future__ import annotations

from typing import ClassVar

from vanta.forecasting.base import ForecastContext, ForecastEngine, Prediction
from vanta.protocol.forecast import Direction
from vanta.validation import VantaValidationError, require_probability

__all__ = ["AdversarialEngine"]


class AdversarialEngine(ForecastEngine):
    """Maximum confidence, fixed direction, no reference to the market at all."""

    name: ClassVar[str] = "adversarial"
    min_history: ClassVar[int] = 0

    def __init__(
        self,
        *,
        confidence: float = 0.99,
        direction: Direction = Direction.UP,
        magnitude: float = 0.02,
    ) -> None:
        confidence = require_probability(confidence, "confidence")
        if confidence <= 0.5:
            raise VantaValidationError(
                f"an overconfident engine needs confidence > 0.5, got {confidence}"
            )
        self._confidence = confidence
        self._direction = direction
        self._magnitude = abs(magnitude)

    def predict(self, context: ForecastContext) -> Prediction:
        bullish = self._direction is Direction.UP
        return Prediction(
            probability_up=self._confidence if bullish else 1.0 - self._confidence,
            expected_return=self._magnitude if bullish else -self._magnitude,
        )
