"""Turn a venue's raw candle list into a trustworthy series (§13).

Venues differ in ordering, field layout, duplicate handling and gap behaviour. Every
provider funnels its parsed candles through :func:`normalize_candles`, so downstream
code can assume one shape: ascending, aligned, contiguous, deduplicated, and confined
to the requested half-open window.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from itertools import pairwise

from vanta.market.errors import MalformedMarketDataError
from vanta.market.provider import Candle

__all__ = ["align_down", "normalize_asset", "normalize_candles"]


def normalize_asset(asset: str) -> str:
    """Return the canonical ``BASE-QUOTE`` form, e.g. ``ETH-USD``."""
    if not isinstance(asset, str):
        raise MalformedMarketDataError(f"asset must be a string, got {asset!r}")
    canonical = asset.strip().upper()
    parts = canonical.split("-")
    if len(parts) != 2 or not all(parts):
        raise MalformedMarketDataError(f"asset must look like 'ETH-USD', got {asset!r}")
    return canonical


def align_down(timestamp: int, interval_seconds: int) -> int:
    """Round ``timestamp`` down to the start of its candle."""
    if interval_seconds <= 0:
        raise MalformedMarketDataError(f"interval_seconds must be > 0, got {interval_seconds!r}")
    return timestamp - (timestamp % interval_seconds)


def normalize_candles(
    candles: Iterable[Candle],
    *,
    interval_seconds: int,
    start_time: int | None = None,
    end_time: int | None = None,
    require_contiguous: bool = True,
) -> list[Candle]:
    """Validate and canonicalize a candle series.

    Args:
        candles: parsed candles in any order.
        interval_seconds: the interval every candle must carry.
        start_time: inclusive lower bound on ``open_time``, if bounding is wanted.
        end_time: exclusive upper bound on ``open_time``.
        require_contiguous: reject gaps in the surviving series. Gaps are treated as an
            error rather than silently interpolated, because a missing candle around a
            resolution instant would otherwise resolve a task against the wrong price.

    Raises:
        MalformedMarketDataError: on a wrong interval, misalignment, conflicting
            duplicates, or a gap when ``require_contiguous`` is set.
    """
    if interval_seconds <= 0:
        raise MalformedMarketDataError(f"interval_seconds must be > 0, got {interval_seconds!r}")

    by_open_time: dict[int, Candle] = {}
    for candle in candles:
        if candle.interval_seconds != interval_seconds:
            raise MalformedMarketDataError(
                f"candle at {candle.open_time} has interval {candle.interval_seconds}s, "
                f"expected {interval_seconds}s"
            )
        if candle.open_time % interval_seconds != 0:
            raise MalformedMarketDataError(
                f"candle open_time {candle.open_time} is not aligned to {interval_seconds}s"
            )
        existing = by_open_time.get(candle.open_time)
        if existing is not None and existing != candle:
            raise MalformedMarketDataError(f"conflicting candles for open_time {candle.open_time}")
        by_open_time[candle.open_time] = candle

    ordered = [by_open_time[key] for key in sorted(by_open_time)]

    if start_time is not None:
        ordered = [candle for candle in ordered if candle.open_time >= start_time]
    if end_time is not None:
        ordered = [candle for candle in ordered if candle.open_time < end_time]

    if require_contiguous:
        _require_contiguous(ordered, interval_seconds)
    return ordered


def _require_contiguous(ordered: Sequence[Candle], interval_seconds: int) -> None:
    for previous, current in pairwise(ordered):
        expected = previous.open_time + interval_seconds
        if current.open_time != expected:
            raise MalformedMarketDataError(
                f"gap in candle series: expected open_time {expected}, got {current.open_time}"
            )
