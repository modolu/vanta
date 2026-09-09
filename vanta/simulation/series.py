"""Bounded chronological access to an in-memory candle series (ARCHITECTURE.md §29, §41).

A replay asks for one causal window per task, thousands of times. Rebuilding that window
by scanning and re-sorting the whole history each time is quadratic and, over a 60-day
1m series, unusably slow.

This cursor keeps the same guarantee at a fraction of the cost: the series is validated
and sorted once up front, a binary search finds the last candle to have closed at the
requested instant, and the window is a bounded slice ending there. The slice still goes
through :class:`MarketWindow`, which re-checks the causal invariant, so the safety
property is enforced, not merely assumed.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Sequence

from vanta.market.errors import InsufficientMarketDataError, StaleMarketDataError
from vanta.market.normalization import normalize_candles
from vanta.market.provider import Candle
from vanta.market.resolution import MarketWindow

__all__ = ["CandleSeries"]


class CandleSeries:
    """An ascending, validated candle history addressable by instant."""

    def __init__(self, candles: Iterable[Candle], *, interval_seconds: int) -> None:
        ordered = normalize_candles(
            candles, interval_seconds=interval_seconds, require_contiguous=False
        )
        if not ordered:
            raise InsufficientMarketDataError("cannot build a series from zero candles")
        self._interval = interval_seconds
        self._candles: tuple[Candle, ...] = tuple(ordered)
        self._close_times: list[int] = [candle.close_time for candle in self._candles]

    def __len__(self) -> int:
        return len(self._candles)

    @property
    def interval_seconds(self) -> int:
        return self._interval

    @property
    def candles(self) -> tuple[Candle, ...]:
        return self._candles

    @property
    def start_time(self) -> int:
        return self._candles[0].open_time

    @property
    def end_time(self) -> int:
        return self._candles[-1].close_time

    def _visible_count(self, as_of: int) -> int:
        """How many candles had closed by ``as_of``."""
        return bisect_right(self._close_times, as_of)

    def window_at(self, as_of: int, lookback: int) -> MarketWindow:
        """The last ``lookback`` candles to have closed at or before ``as_of``."""
        if lookback < 1:
            raise ValueError(f"lookback must be >= 1, got {lookback}")
        end = self._visible_count(as_of)
        if end == 0:
            raise InsufficientMarketDataError(f"no candles closed at or before {as_of}")
        start = max(0, end - lookback)
        return MarketWindow(as_of=as_of, candles=self._candles[start:end])

    def price_at(self, as_of: int, *, max_staleness_seconds: int) -> float:
        """Close of the last candle to have closed by ``as_of``."""
        end = self._visible_count(as_of)
        if end == 0:
            raise InsufficientMarketDataError(f"no candles closed at or before {as_of}")
        latest = self._candles[end - 1]
        staleness = as_of - latest.close_time
        if staleness > max_staleness_seconds:
            raise StaleMarketDataError(
                f"freshest candle closed at {latest.close_time}, {staleness}s before "
                f"{as_of} (tolerance {max_staleness_seconds}s)"
            )
        return latest.close

    def task_times(
        self, *, spacing_seconds: int, warmup_candles: int, horizon_seconds: int
    ) -> list[int]:
        """Chronological task instants that have both warm-up history and an outcome."""
        if spacing_seconds < 1:
            raise ValueError(f"spacing_seconds must be >= 1, got {spacing_seconds}")
        first = self._candles[min(warmup_candles, len(self._candles) - 1)].close_time
        last = self.end_time - horizon_seconds
        times: list[int] = []
        current = first
        while current <= last:
            times.append(current)
            current += spacing_seconds
        return times

    @classmethod
    def from_sequence(cls, candles: Sequence[Candle], *, interval_seconds: int) -> CandleSeries:
        return cls(candles, interval_seconds=interval_seconds)
