"""Persistence engine (ARCHITECTURE.md §11, miner 2).

Assumes the recent drift continues: a positive recent return is bullish, a negative one
bearish. The simplest forecast that is not noise, and a useful floor for the leaderboard.
"""

from __future__ import annotations

import math
from typing import ClassVar

from vanta.forecasting.base import ForecastContext, ForecastEngine, Prediction
from vanta.forecasting.features import (
    bounded_probability,
    logistic,
    period_return,
    volatility_of,
)

__all__ = ["PersistenceEngine"]


class PersistenceEngine(ForecastEngine):
    """Extrapolates the recent move forward, damped."""

    name: ClassVar[str] = "persistence"
    min_history: ClassVar[int] = 21

    def __init__(
        self,
        *,
        lookback: int = 5,
        volatility_window: int = 20,
        steepness: float = 0.8,
        damping: float = 0.5,
    ) -> None:
        self._lookback = lookback
        self._volatility_window = volatility_window
        self._steepness = steepness
        # Pure extrapolation overshoots, so only part of the recent drift is carried
        # forward into the expected return.
        self._damping = damping

    def predict(self, context: ForecastContext) -> Prediction:
        closes = context.closes
        recent = period_return(closes, self._lookback)
        volatility = volatility_of(closes, self._volatility_window)
        # Per-candle volatility scaled to the length of the move being measured.
        scale = (volatility if volatility > 0.0 else 1e-9) * math.sqrt(self._lookback)

        signal = recent / scale
        per_step = recent / self._lookback
        expected = per_step * context.horizon_steps * self._damping

        return Prediction(
            probability_up=bounded_probability(logistic(signal, self._steepness)),
            expected_return=expected,
        )
