from __future__ import annotations

from pathlib import Path

import pytest

from tests.market.helpers import make_series
from vanta.market.cache import CachedProvider, HistoricalCandleCache
from vanta.market.errors import MalformedMarketDataError
from vanta.market.provider import Candle, MarketDataProvider


class _CountingProvider(MarketDataProvider):
    name = "counting"

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles
        self.calls = 0

    def fetch_candles(
        self, asset: str, interval_seconds: int, start_time: int, end_time: int
    ) -> list[Candle]:
        self.calls += 1
        return [c for c in self._candles if start_time <= c.open_time < end_time]


class TestHistoricalCandleCache:
    def test_round_trips_a_series(self, tmp_path: Path) -> None:
        cache = HistoricalCandleCache(tmp_path)
        candles = make_series(60, [100.0, 101.0, 102.0])
        cache.extend("ETH-USD", 60, candles)
        assert cache.load("ETH-USD", 60) == candles

    def test_missing_file_loads_empty(self, tmp_path: Path) -> None:
        assert HistoricalCandleCache(tmp_path).load("ETH-USD", 60) == []

    def test_merges_and_deduplicates_across_writes(self, tmp_path: Path) -> None:
        cache = HistoricalCandleCache(tmp_path)
        cache.extend("ETH-USD", 60, make_series(60, [100.0, 101.0]))
        cache.extend("ETH-USD", 60, make_series(120, [101.0, 102.0]))
        stored = cache.load("ETH-USD", 60)
        assert [c.open_time for c in stored] == [60, 120, 180]

    def test_get_returns_none_when_coverage_is_incomplete(self, tmp_path: Path) -> None:
        cache = HistoricalCandleCache(tmp_path)
        cache.extend("ETH-USD", 60, make_series(60, [100.0, 101.0]))
        assert cache.get("ETH-USD", 60, 60, 300) is None

    def test_get_returns_the_window_when_fully_covered(self, tmp_path: Path) -> None:
        cache = HistoricalCandleCache(tmp_path)
        cache.extend("ETH-USD", 60, make_series(60, [100.0, 101.0, 102.0, 103.0]))
        window = cache.get("ETH-USD", 60, 120, 240)
        assert window is not None
        assert [c.open_time for c in window] == [120, 180]

    def test_a_gap_inside_the_range_is_a_miss(self, tmp_path: Path) -> None:
        cache = HistoricalCandleCache(tmp_path)
        cache.extend("ETH-USD", 60, [*make_series(60, [100.0]), *make_series(180, [102.0])])
        assert cache.get("ETH-USD", 60, 60, 240) is None

    def test_separate_intervals_use_separate_files(self, tmp_path: Path) -> None:
        cache = HistoricalCandleCache(tmp_path)
        assert cache.path_for("ETH-USD", 60) != cache.path_for("ETH-USD", 900)

    def test_corrupt_cache_file_fails_explicitly(self, tmp_path: Path) -> None:
        cache = HistoricalCandleCache(tmp_path)
        path = cache.path_for("ETH-USD", 60)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(MalformedMarketDataError, match="not valid JSON"):
            cache.load("ETH-USD", 60)

    def test_writing_leaves_no_temporary_file(self, tmp_path: Path) -> None:
        cache = HistoricalCandleCache(tmp_path)
        cache.extend("ETH-USD", 60, make_series(60, [100.0]))
        assert list(tmp_path.glob("*.tmp")) == []

    def test_extending_with_nothing_is_a_no_op(self, tmp_path: Path) -> None:
        cache = HistoricalCandleCache(tmp_path)
        cache.extend("ETH-USD", 60, [])
        assert not cache.path_for("ETH-USD", 60).exists()


class TestCachedProvider:
    def test_first_call_hits_upstream_and_second_does_not(self, tmp_path: Path) -> None:
        upstream = _CountingProvider(make_series(60, [100.0, 101.0, 102.0]))
        provider = CachedProvider(upstream, HistoricalCandleCache(tmp_path))

        first = provider.fetch_candles("ETH-USD", 60, 60, 240)
        second = provider.fetch_candles("ETH-USD", 60, 60, 240)

        assert first == second
        assert upstream.calls == 1

    def test_survives_a_new_cache_instance(self, tmp_path: Path) -> None:
        upstream = _CountingProvider(make_series(60, [100.0, 101.0, 102.0]))
        CachedProvider(upstream, HistoricalCandleCache(tmp_path)).fetch_candles(
            "ETH-USD", 60, 60, 240
        )
        CachedProvider(upstream, HistoricalCandleCache(tmp_path)).fetch_candles(
            "ETH-USD", 60, 60, 240
        )
        assert upstream.calls == 1

    def test_uncovered_range_goes_upstream(self, tmp_path: Path) -> None:
        upstream = _CountingProvider(make_series(60, [100.0, 101.0, 102.0, 103.0]))
        provider = CachedProvider(upstream, HistoricalCandleCache(tmp_path))
        provider.fetch_candles("ETH-USD", 60, 60, 180)
        provider.fetch_candles("ETH-USD", 60, 60, 300)
        assert upstream.calls == 2
