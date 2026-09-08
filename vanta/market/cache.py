"""Simple on-disk candle cache for historical replay (§41).

One JSON file per ``(asset, interval)``, holding an ascending, deduplicated candle
series. Historical candles are immutable once closed, so a hit is always as good as a
refetch — and the Phase 4 simulation can replay thousands of tasks without hammering a
public API or depending on the network at all.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, ClassVar

from vanta.log import get_logger
from vanta.market.errors import MalformedMarketDataError
from vanta.market.normalization import normalize_asset, normalize_candles
from vanta.market.provider import Candle, MarketDataProvider

__all__ = ["CachedProvider", "HistoricalCandleCache"]

logger = get_logger(__name__)


class HistoricalCandleCache:
    """Append-only candle store rooted at a directory."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def path_for(self, asset: str, interval_seconds: int) -> Path:
        return self._root / f"{normalize_asset(asset).replace('-', '')}_{interval_seconds}s.json"

    def load(self, asset: str, interval_seconds: int) -> list[Candle]:
        """Return every cached candle for this series, ascending."""
        path = self.path_for(asset, interval_seconds)
        if not path.exists():
            return []
        try:
            rows: Any = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise MalformedMarketDataError(f"cache file {path} is not valid JSON: {exc}") from exc
        if not isinstance(rows, list):
            raise MalformedMarketDataError(f"cache file {path} does not contain a list")
        candles = [
            Candle(
                open_time=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                interval_seconds=interval_seconds,
            )
            for row in rows
        ]
        return normalize_candles(
            candles, interval_seconds=interval_seconds, require_contiguous=False
        )

    def get(
        self, asset: str, interval_seconds: int, start_time: int, end_time: int
    ) -> list[Candle] | None:
        """Return the requested window, or ``None`` if the cache does not fully cover it."""
        if end_time <= start_time:
            return []
        cached = [
            candle
            for candle in self.load(asset, interval_seconds)
            if start_time <= candle.open_time < end_time
        ]
        expected = (end_time - start_time) // interval_seconds
        if not cached or len(cached) < expected:
            return None
        try:
            return normalize_candles(
                cached,
                interval_seconds=interval_seconds,
                start_time=start_time,
                end_time=end_time,
            )
        except MalformedMarketDataError:
            # A gap inside the cached range is a miss, not a failure — refetch instead.
            return None

    def extend(self, asset: str, interval_seconds: int, candles: list[Candle]) -> None:
        """Merge ``candles`` into the stored series and rewrite the file atomically."""
        if not candles:
            return
        merged = normalize_candles(
            [*self.load(asset, interval_seconds), *candles],
            interval_seconds=interval_seconds,
            require_contiguous=False,
        )
        path = self.path_for(asset, interval_seconds)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [[c.open_time, c.open, c.high, c.low, c.close, c.volume] for c in merged]
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temporary, path)


class CachedProvider(MarketDataProvider):
    """Wraps a provider, serving fully-covered windows from disk."""

    name: ClassVar[str] = "cached"

    def __init__(self, provider: MarketDataProvider, cache: HistoricalCandleCache) -> None:
        self._provider = provider
        self._cache = cache

    @property
    def upstream(self) -> MarketDataProvider:
        return self._provider

    def fetch_candles(
        self, asset: str, interval_seconds: int, start_time: int, end_time: int
    ) -> list[Candle]:
        hit = self._cache.get(asset, interval_seconds, start_time, end_time)
        if hit is not None:
            logger.debug("cache hit %s %ss [%s, %s)", asset, interval_seconds, start_time, end_time)
            return hit
        fetched = self._provider.fetch_candles(asset, interval_seconds, start_time, end_time)
        self._cache.extend(asset, interval_seconds, fetched)
        return fetched
