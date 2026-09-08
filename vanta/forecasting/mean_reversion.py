"""Mean-reversion engine (ARCHITECTURE.md §11, miner 3).

The mirror of persistence: an unusually large recent move raises the probability that the
next horizon retraces it. The move is measured in units of realized volatility, so
"unusually large" adapts to the regime instead of being a fixed percentage.
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

__all__ = ["MeanReversionEngine"]


class MeanReversionEngine(ForecastEngine):
    """Fades the recent move in proportion to how extreme it was."""

    name: ClassVar[str] = "mean-reversion"
    min_history: ClassVar[int] = 21

    def __init__(
        self,
        *,
        lookback: int = 5,
        volatility_window: int = 20,
        steepness: float = 0.8,
        reversion_fraction: float = 0.3,
    ) -> None:
        self._lookback = lookback
        self._volatility_window = volatility_window
        self._steepness = steepness
        self._reversion_fraction = reversion_fraction

    def predict(self, context: ForecastContext) -> Prediction:
        closes = context.closes
        move = period_return(closes, self._lookback)
        volatility = volatility_of(closes, self._volatility_window)
        # Per-candle volatility scaled to the length of the move being measured.
        scale = (volatility if volatility > 0.0 else 1e-9) * math.sqrt(self._lookback)

        # Negated: the stronger the rally, the more bearish this engine becomes.
        signal = -move / scale

        return Prediction(
            probability_up=bounded_probability(logistic(signal, self._steepness)),
            expected_return=-move * self._reversion_fraction,
        )
