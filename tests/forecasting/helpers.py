"""Synthetic price series and context builders for the engine tests.

Every series is generated deterministically — no RNG, no network, no fixtures — so the
engines' reactions can be asserted exactly.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from vanta.forecasting.base import ForecastContext
from vanta.market.provider import Candle
from vanta.protocol.forecast import ForecastTask

T = 1_788_900_000  # 60-aligned
INTERVAL = 60
HORIZON = 900
WARMUP = 200  # comfortably above every engine's history requirement


def make_task(
    *, timestamp: int = T, reference_price: float = 4500.0, horizon: int = HORIZON
) -> ForecastTask:
    return ForecastTask(
        task_id=f"eth-{horizon}s-{timestamp}",
        asset="ETH-USD",
        reference_price=reference_price,
        timestamp=timestamp,
        horizon_seconds=horizon,
        deadline=timestamp + 30,
    )


def candles_from(closes: Sequence[float], *, start: int, interval: int = INTERVAL) -> list[Candle]:
    """A contiguous candle series whose OHLC bracket contains each close."""
    return [
        Candle(
            open_time=start + index * interval,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=10.0,
            interval_seconds=interval,
        )
        for index, close in enumerate(closes)
    ]


def context_ending_at(
    closes: Sequence[float], *, timestamp: int = T, horizon: int = HORIZON
) -> ForecastContext:
    """Build a context whose last visible candle closes exactly at ``timestamp``."""
    start = timestamp - len(closes) * INTERVAL
    task = make_task(timestamp=timestamp, reference_price=closes[-1], horizon=horizon)
    return ForecastContext.build(task, candles_from(closes, start=start))


def flat(length: int = WARMUP, price: float = 4000.0) -> list[float]:
    return [price] * length


def trend(length: int = WARMUP, *, start: float = 4000.0, step: float = 0.0008) -> list[float]:
    """A compounding drift with a small deterministic wobble.

    The wobble matters: a perfectly smooth geometric series has zero variance of returns,
    so any volatility-normalized signal divides by ~0 and saturates. Real price series
    always carry noise, and testing against a degenerate one would prove nothing.
    """
    wobble = abs(step) * 0.25
    prices = [start]
    for index in range(length - 1):
        drift = 1.0 + step + wobble * math.sin(index / 2.0)
        prices.append(prices[-1] * drift)
    return prices


def choppy(length: int = WARMUP, *, start: float = 4000.0, amplitude: float = 0.004) -> list[float]:
    """A deterministic oscillation with no net drift — mean-reverting by construction."""
    return [start * (1.0 + amplitude * math.sin(index / 3.0)) for index in range(length)]


def spike(
    length: int = WARMUP,
    *,
    start: float = 4000.0,
    size: float = 0.05,
    run: int = 5,
    baseline_amplitude: float = 0.0006,
) -> list[float]:
    """A directionless but noisy series ending in a sharp move over the last ``run``.

    The baseline wobbles rather than sitting perfectly flat, so realized volatility is
    non-zero and the move's size can actually be measured against it. On a dead-flat
    baseline every spike, however small, reads as infinitely extreme.
    """
    prices = [
        start * (1.0 + baseline_amplitude * math.sin(index / 3.0)) for index in range(length - run)
    ]
    last = prices[-1]
    for index in range(run):
        prices.append(last * (1.0 + size * (index + 1) / run))
    return prices
