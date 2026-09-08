"""Small, pure indicator helpers shared by the reference engines.

Deliberately minimal (§11): enough to express momentum and reversion, not a technical
analysis library. Every function is a pure transform of a close series and raises rather
than returning a sentinel when the series is too short.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from vanta.market.errors import InsufficientMarketDataError
from vanta.market.resolution import realized_volatility

__all__ = [
    "bounded_probability",
    "ema",
    "feature_row",
    "logistic",
    "period_return",
    "roc",
    "rsi",
    "simple_returns",
    "volatility_of",
]

# Feature-row layout, shared by the momentum and ML engines so a fitted model and a
# hand-weighted one describe the same market in the same terms.
FEATURE_NAMES = ("return_1", "return_5", "ema_gap", "rsi_centered", "volatility")
FEATURE_WARMUP = 21

# No honest engine should ever claim certainty. Brier scoring punishes a confident miss
# far harder than a hedged one (§16), and a degenerate market — a perfectly steady drift
# with no return variance — otherwise saturates a volatility-normalized signal straight to
# 0 or 1. The adversarial engine deliberately opts out of this bound.
MAX_HONEST_CONFIDENCE = 0.99


def bounded_probability(probability: float, limit: float = MAX_HONEST_CONFIDENCE) -> float:
    """Keep a probability inside ``[1 - limit, limit]``."""
    return min(limit, max(1.0 - limit, probability))


def logistic(value: float, steepness: float = 1.0) -> float:
    """Squash a signed signal into ``(0, 1)``, overflow-safe at either extreme."""
    z = steepness * value
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-min(z, 700.0)))
    exponential = math.exp(max(z, -700.0))
    return exponential / (1.0 + exponential)


def _require_length(prices: Sequence[float], needed: int, what: str) -> None:
    if len(prices) < needed:
        raise InsufficientMarketDataError(f"{what} needs {needed} prices, got {len(prices)}")


def simple_returns(prices: Sequence[float]) -> list[float]:
    """Period-over-period simple returns."""
    _require_length(prices, 2, "simple_returns")
    return [(later - earlier) / earlier for earlier, later in pairwise(prices) if earlier > 0]


def period_return(prices: Sequence[float], period: int) -> float:
    """Return over the last ``period`` steps."""
    if period < 1:
        raise InsufficientMarketDataError(f"period must be >= 1, got {period}")
    _require_length(prices, period + 1, "period_return")
    earlier = prices[-1 - period]
    if earlier <= 0:
        raise InsufficientMarketDataError("cannot compute a return from a non-positive price")
    return (prices[-1] - earlier) / earlier


def ema(prices: Sequence[float], period: int) -> float:
    """Exponential moving average of the series, seeded on its first value."""
    if period < 1:
        raise InsufficientMarketDataError(f"period must be >= 1, got {period}")
    _require_length(prices, period, "ema")
    alpha = 2.0 / (period + 1.0)
    value = prices[0]
    for price in prices[1:]:
        value = alpha * price + (1.0 - alpha) * value
    return value


def roc(prices: Sequence[float], period: int) -> float:
    """Rate of change over ``period`` steps, as a fraction."""
    return period_return(prices, period)


def rsi(prices: Sequence[float], period: int = 14) -> float:
    """Relative strength index over the last ``period`` changes, on a 0-100 scale."""
    if period < 1:
        raise InsufficientMarketDataError(f"period must be >= 1, got {period}")
    _require_length(prices, period + 1, "rsi")
    changes = [later - earlier for earlier, later in pairwise(prices[-period - 1 :])]
    gains = sum(change for change in changes if change > 0) / period
    losses = -sum(change for change in changes if change < 0) / period
    if losses == 0.0:
        return 100.0 if gains > 0.0 else 50.0
    relative_strength = gains / losses
    return 100.0 - (100.0 / (1.0 + relative_strength))


def volatility_of(prices: Sequence[float], window: int) -> float:
    """Per-candle realized volatility over the last ``window`` steps."""
    _require_length(prices, window + 1, "volatility_of")
    return realized_volatility(list(prices[-window - 1 :]))


def feature_row(prices: Sequence[float], *, volatility_window: int = 20) -> list[float]:
    """The shared feature vector: short and medium returns, EMA gap, RSI, volatility.

    Returns and the EMA gap are divided by realized volatility so the row means the same
    thing in a calm market as in a violent one. A multi-step return is divided by
    ``volatility * sqrt(steps)``: volatility is quoted per candle, so comparing a 5-candle
    move against it directly overstates the move by a factor of sqrt(5) and saturates any
    squashing function that follows.
    """
    _require_length(prices, FEATURE_WARMUP, "feature_row")
    volatility = volatility_of(prices, volatility_window)
    scale = volatility if volatility > 0.0 else 1e-9
    last = prices[-1]
    ema_gap = (ema(prices[-12:], 4) - ema(prices[-12:], 12)) / last
    return [
        period_return(prices, 1) / scale,
        period_return(prices, 5) / (scale * math.sqrt(5)),
        ema_gap / scale,
        (rsi(prices, 14) - 50.0) / 50.0,
        volatility,
    ]
