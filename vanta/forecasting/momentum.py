"""Momentum engine (ARCHITECTURE.md §11, miner 4).

Blends the shared feature row — short and medium returns, an EMA gap, RSI — into a single
signed signal with hand-set weights. The weights are fixed constants chosen for their
sign and rough magnitude; nothing here is fitted, so there is no data to leak from.
"""

from __future__ import annotations

import math
from typing import ClassVar

from vanta.forecasting.base import ForecastContext, ForecastEngine, Prediction
from vanta.forecasting.features import (
    FEATURE_WARMUP,
    bounded_probability,
    feature_row,
    logistic,
)

__all__ = ["MomentumEngine"]

# Aligned with FEATURE_NAMES: return_1, return_5, ema_gap, rsi_centered, volatility.
# Volatility carries weight 0.0 — it is a normalizer for the other features and a
# regime descriptor, not a directional signal.
FEATURE_WEIGHTS = (0.25, 0.45, 0.35, 0.60, 0.0)


class MomentumEngine(ForecastEngine):
    """Trend-following: agreement across the feature row raises confidence."""

    name: ClassVar[str] = "momentum"
    min_history: ClassVar[int] = FEATURE_WARMUP

    def __init__(self, *, volatility_window: int = 20, steepness: float = 0.9) -> None:
        self._volatility_window = volatility_window
        self._steepness = steepness

    def predict(self, context: ForecastContext) -> Prediction:
        closes = context.closes
        features = feature_row(closes, volatility_window=self._volatility_window)
        signal = sum(
            weight * value for weight, value in zip(FEATURE_WEIGHTS, features, strict=True)
        )

        probability = bounded_probability(logistic(signal, self._steepness))
        # A typical move over the horizon is per-candle volatility scaled by sqrt(steps);
        # the directional edge (2p - 1) says how much of it to claim, and in which way.
        horizon_scale = features[-1] * math.sqrt(context.horizon_steps)
        return Prediction(
            probability_up=probability,
            expected_return=(2.0 * probability - 1.0) * horizon_scale,
        )
