"""Reference prices, ground-truth resolution, and the volatility-derived return scale.

ARCHITECTURE.md §14 (resolution), §17 (return score scale), §29 (no look-ahead).

The leakage guard is structural: every price lookup goes through :class:`MarketWindow`,
which discards candles closing after its ``as_of`` instant at construction. Code holding
a window cannot reach data from after that instant, so a look-ahead bug cannot be written
by accident (§29).
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise

from vanta.log import get_logger
from vanta.market.errors import (
    InsufficientMarketDataError,
    LookaheadError,
    StaleMarketDataError,
)
from vanta.market.normalization import align_down
from vanta.market.provider import Candle, MarketDataProvider
from vanta.protocol.forecast import ForecastTask, Resolution

__all__ = [
    "DEFAULT_MAX_STALENESS_INTERVALS",
    "DEFAULT_MIN_VOLATILITY_SAMPLES",
    "DEFAULT_VOLATILITY_LOOKBACK_PERIODS",
    "MarketWindow",
    "ResolutionEngine",
    "price_at",
    "realized_volatility",
    "return_scale_from_closes",
]

logger = get_logger(__name__)

# Operational tolerances, not mechanism rules. A price lookup accepts a candle that
# closed up to this many intervals before the requested instant, covering ordinary venue
# gaps without silently pricing a task against stale data.
DEFAULT_MAX_STALENESS_INTERVALS = 2

# Horizon-length periods sampled when estimating volatility: 96 x 15m is 24 hours, long
# enough to average over a session but short enough to track the current regime.
DEFAULT_VOLATILITY_LOOKBACK_PERIODS = 96

# Below this many horizon returns the standard deviation is too noisy to normalize by.
DEFAULT_MIN_VOLATILITY_SAMPLES = 20


@dataclass(frozen=True, slots=True)
class MarketWindow:
    """Candles visible at ``as_of``. Later data is unreachable by construction (§29)."""

    as_of: int
    candles: tuple[Candle, ...]

    def __post_init__(self) -> None:
        """Enforce the causal invariant on every construction path, not just ``build``.

        Constructing a window directly with a candle from after ``as_of`` is rejected, so
        the boundary cannot be bypassed by building the dataclass by hand.
        """
        previous = -1
        for candle in self.candles:
            if candle.close_time > self.as_of:
                raise LookaheadError(
                    f"candle closing at {candle.close_time} is after the window instant "
                    f"{self.as_of}; a causal view cannot hold future data"
                )
            if candle.open_time <= previous:
                raise LookaheadError("candles must be strictly ascending by open_time")
            previous = candle.open_time

    @classmethod
    def build(cls, candles: Iterable[Candle], as_of: int) -> MarketWindow:
        """Keep only candles that have *closed* at or before ``as_of``.

        A candle whose ``close_time`` exceeds ``as_of`` is still forming and its close
        price is not yet knowable, so including it would leak the future.
        """
        visible = tuple(
            sorted(
                (candle for candle in candles if candle.close_time <= as_of),
                key=lambda candle: candle.open_time,
            )
        )
        return cls(as_of=as_of, candles=visible)

    def __bool__(self) -> bool:
        return bool(self.candles)

    @property
    def latest(self) -> Candle:
        if not self.candles:
            raise InsufficientMarketDataError(f"no candles closed at or before {self.as_of}")
        return self.candles[-1]

    @property
    def latest_close(self) -> float:
        return self.latest.close

    def closes(self) -> tuple[float, ...]:
        return tuple(candle.close for candle in self.candles)


def price_at(
    candles: Iterable[Candle],
    timestamp: int,
    *,
    max_staleness_seconds: int,
) -> float:
    """The market price at ``timestamp``: the close of the last candle to close by then.

    Raises:
        InsufficientMarketDataError: if nothing has closed by ``timestamp``.
        StaleMarketDataError: if the freshest close is older than the tolerance.
    """
    window = MarketWindow.build(candles, timestamp)
    latest = window.latest
    staleness = timestamp - latest.close_time
    if staleness > max_staleness_seconds:
        raise StaleMarketDataError(
            f"freshest candle closed at {latest.close_time}, {staleness}s before the "
            f"requested instant {timestamp} (tolerance {max_staleness_seconds}s)"
        )
    return latest.close


def realized_volatility(prices: Sequence[float]) -> float:
    """Standard deviation of simple returns between consecutive prices.

    Used as the ``scale`` of the §17 return score, so that an error of one typical move
    costs the same amount whatever the market regime.
    """
    if len(prices) < 3:
        raise InsufficientMarketDataError(
            f"need at least 3 prices to estimate volatility, got {len(prices)}"
        )
    returns = [(later - earlier) / earlier for earlier, later in pairwise(prices) if earlier > 0]
    if len(returns) < 2:
        raise InsufficientMarketDataError("not enough usable returns to estimate volatility")
    return statistics.stdev(returns)


def return_scale_from_closes(
    closes: Sequence[float], horizon_steps: int, *, min_samples: int
) -> float:
    """Volatility of ``horizon_steps``-spaced returns within an already-bounded series.

    Shared by the live resolution engine and the historical replay so both derive the
    §17 scale identically. ``closes`` must already be causal; this function does not
    bound anything itself.
    """
    if horizon_steps < 1:
        raise ValueError(f"horizon_steps must be >= 1, got {horizon_steps}")
    # Subsample backwards from the most recent close so samples sit exactly one horizon
    # apart and end at the visible edge.
    sampled = closes[::-1][::horizon_steps][::-1]
    if len(sampled) - 1 < min_samples:
        raise InsufficientMarketDataError(
            f"need {min_samples} horizon returns to estimate scale, got {max(len(sampled) - 1, 0)}"
        )
    scale = realized_volatility(sampled)
    if scale <= 0.0:
        raise InsufficientMarketDataError(
            "observed volatility is zero; cannot normalize return errors"
        )
    return scale


class ResolutionEngine:
    """Prices tasks against a provider and turns realized moves into ground truth (§14)."""

    def __init__(
        self,
        provider: MarketDataProvider,
        *,
        candle_interval_seconds: int = 60,
        max_staleness_intervals: int = DEFAULT_MAX_STALENESS_INTERVALS,
        volatility_lookback_periods: int = DEFAULT_VOLATILITY_LOOKBACK_PERIODS,
        min_volatility_samples: int = DEFAULT_MIN_VOLATILITY_SAMPLES,
    ) -> None:
        if candle_interval_seconds <= 0:
            raise ValueError("candle_interval_seconds must be > 0")
        if max_staleness_intervals < 0:
            raise ValueError("max_staleness_intervals must be >= 0")
        self._provider = provider
        self._interval = candle_interval_seconds
        self._max_staleness = max_staleness_intervals * candle_interval_seconds
        self._lookback_periods = volatility_lookback_periods
        self._min_samples = min_volatility_samples

    @property
    def interval_seconds(self) -> int:
        return self._interval

    def price_at(self, asset: str, timestamp: int) -> float:
        """Fetch a short window ending at ``timestamp`` and return the price there."""
        lookback = (self._max_staleness // self._interval + 4) * self._interval
        start = align_down(timestamp - lookback, self._interval)
        candles = self._provider.fetch_candles(asset, self._interval, start, timestamp)
        return price_at(candles, timestamp, max_staleness_seconds=self._max_staleness)

    def reference_price(self, asset: str, timestamp: int) -> float:
        """Price recorded when a task is generated (§7)."""
        return self.price_at(asset, timestamp)

    def resolution_price(self, task: ForecastTask) -> float:
        """Price at ``task.resolve_at``, the instant the outcome becomes known."""
        return self.price_at(task.asset, task.resolve_at)

    def resolve(self, task: ForecastTask) -> Resolution:
        """Produce ground truth for ``task``.

        The reference price is the one fixed at task creation, never refetched, so the
        realized return always measures the move the miners were actually asked about.
        """
        return Resolution.from_task(task, resolution_price=self.resolution_price(task))

    def return_scale(self, asset: str, as_of: int, horizon_seconds: int) -> float:
        """Volatility of ``horizon_seconds`` returns observed up to ``as_of`` (§17).

        Sampled from base-interval candles subsampled at the horizon, so any horizon
        that is a multiple of the candle interval works without a dedicated feed.
        """
        if horizon_seconds <= 0 or horizon_seconds % self._interval != 0:
            raise ValueError(
                f"horizon_seconds must be a positive multiple of {self._interval}, "
                f"got {horizon_seconds}"
            )
        step = horizon_seconds // self._interval
        span = self._lookback_periods * horizon_seconds
        start = align_down(as_of - span, self._interval)
        candles = self._provider.fetch_candles(asset, self._interval, start, as_of)

        window = MarketWindow.build(candles, as_of)
        scale = return_scale_from_closes(window.closes(), step, min_samples=self._min_samples)
        logger.debug("return scale for %s at %s: %.6f", asset, as_of, scale)
        return scale
