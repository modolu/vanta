"""Deterministic synthetic histories for the simulation tests. No network, no RNG."""

from __future__ import annotations

import math

from tests.forecasting.helpers import candles_from
from vanta.simulation.replay import DatasetInfo, SimulationConfig
from vanta.simulation.series import CandleSeries

START = 1_788_000_000  # 60-aligned
INTERVAL = 60


def synthetic_closes(count: int, *, start: float = 4000.0, seed: float = 1.0) -> list[float]:
    """A mean-reverting series with drift bursts, built from fixed trigonometry.

    Deterministic by construction — the same count always yields the same prices — while
    still carrying enough variance that volatility normalization behaves realistically.
    """
    prices = [start]
    for index in range(1, count):
        wave = 0.0012 * math.sin(index / 17.0 * seed)
        ripple = 0.0006 * math.sin(index / 3.0 + seed)
        drift = 0.0004 * math.sin(index / 211.0)
        prices.append(prices[-1] * (1.0 + wave + ripple + drift))
    return prices


def make_series(count: int = 3000, *, seed: float = 1.0) -> CandleSeries:
    closes = synthetic_closes(count, seed=seed)
    return CandleSeries(candles_from(closes, start=START), interval_seconds=INTERVAL)


def make_dataset(series: CandleSeries) -> DatasetInfo:
    return DatasetInfo(
        source="synthetic",
        symbol="ETH-USD",
        interval_seconds=series.interval_seconds,
        start_time=series.start_time,
        end_time=series.end_time,
        candle_count=len(series),
    )


def small_config(**overrides: object) -> SimulationConfig:
    """A config whose warm-up fits inside a short synthetic series."""
    defaults: dict[str, object] = {
        "lookback_candles": 400,
        "volatility_min_samples": 20,
        "checkpoints": (10, 50),
    }
    defaults.update(overrides)
    return SimulationConfig(**defaults)  # type: ignore[arg-type]
