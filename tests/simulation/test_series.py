from __future__ import annotations

from itertools import pairwise

import pytest

from tests.forecasting.helpers import candles_from
from tests.simulation.helpers import INTERVAL, START, make_series, synthetic_closes
from vanta.market.errors import InsufficientMarketDataError, StaleMarketDataError
from vanta.simulation.series import CandleSeries


class TestBoundedCursor:
    def test_window_never_contains_future_candles(self) -> None:
        series = make_series(500)
        as_of = START + 300 * INTERVAL
        window = series.window_at(as_of, 100)
        assert all(candle.close_time <= as_of for candle in window.candles)
        assert window.as_of == as_of

    def test_window_is_bounded_to_the_lookback(self) -> None:
        series = make_series(500)
        window = series.window_at(START + 400 * INTERVAL, 50)
        assert len(window.candles) == 50

    def test_window_matches_an_unbounded_rebuild_of_the_same_instant(self) -> None:
        # The fast cursor must agree exactly with the slow, obviously-correct path.
        from vanta.market.resolution import MarketWindow

        closes = synthetic_closes(400)
        candles = candles_from(closes, start=START)
        series = CandleSeries(candles, interval_seconds=INTERVAL)
        as_of = START + 250 * INTERVAL

        fast = series.window_at(as_of, 10_000)
        slow = MarketWindow.build(candles, as_of)
        assert fast.candles == slow.candles

    def test_price_at_returns_the_last_closed_candle(self) -> None:
        series = make_series(100)
        as_of = START + 50 * INTERVAL
        assert series.price_at(as_of, max_staleness_seconds=120) == series.candles[49].close

    def test_price_before_any_candle_closes_fails(self) -> None:
        series = make_series(100)
        with pytest.raises(InsufficientMarketDataError):
            series.price_at(START, max_staleness_seconds=120)

    def test_price_past_the_end_is_stale(self) -> None:
        series = make_series(100)
        with pytest.raises(StaleMarketDataError):
            series.price_at(series.end_time + 10_000, max_staleness_seconds=120)

    def test_empty_series_is_rejected(self) -> None:
        with pytest.raises(InsufficientMarketDataError, match="zero candles"):
            CandleSeries([], interval_seconds=INTERVAL)


class TestTaskTimes:
    def test_are_chronological_and_evenly_spaced(self) -> None:
        series = make_series(1000)
        times = series.task_times(spacing_seconds=900, warmup_candles=400, horizon_seconds=900)
        assert times == sorted(times)
        assert all(later - earlier == 900 for earlier, later in pairwise(times))

    def test_every_task_leaves_room_to_resolve(self) -> None:
        series = make_series(1000)
        times = series.task_times(spacing_seconds=900, warmup_candles=400, horizon_seconds=900)
        assert all(time + 900 <= series.end_time for time in times)

    def test_warmup_is_respected(self) -> None:
        series = make_series(1000)
        times = series.task_times(spacing_seconds=900, warmup_candles=400, horizon_seconds=900)
        assert times[0] >= series.start_time + 400 * INTERVAL
