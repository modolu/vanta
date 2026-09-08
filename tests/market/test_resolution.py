from __future__ import annotations

import math

import pytest

from tests.market.helpers import make_candle, make_series
from vanta.market.errors import InsufficientMarketDataError, StaleMarketDataError
from vanta.market.provider import Candle, MarketDataProvider
from vanta.market.resolution import (
    MarketWindow,
    ResolutionEngine,
    price_at,
    realized_volatility,
)
from vanta.protocol.forecast import Direction, ForecastTask

T = 1_788_900_000  # 60-aligned
HORIZON = 900


class _SeriesProvider(MarketDataProvider):
    name = "series"

    def __init__(self, candles: list[Candle]) -> None:
        self._candles = candles

    def fetch_candles(
        self, asset: str, interval_seconds: int, start_time: int, end_time: int
    ) -> list[Candle]:
        return [c for c in self._candles if start_time <= c.open_time < end_time]


def make_task(reference_price: float = 4500.0) -> ForecastTask:
    return ForecastTask(
        task_id="eth-15m-1",
        asset="ETH-USD",
        reference_price=reference_price,
        timestamp=T,
        horizon_seconds=HORIZON,
        deadline=T + 30,
    )


class TestMarketWindow:
    def test_excludes_candles_that_have_not_closed(self) -> None:
        # §29: a candle closing after as_of is still forming; its close is not knowable.
        candles = make_series(T, [100.0, 101.0, 102.0])  # close at T+60, T+120, T+180
        window = MarketWindow.build(candles, T + 120)
        assert [c.open_time for c in window.candles] == [T, T + 60]
        assert window.latest_close == 101.0

    def test_future_data_is_unreachable_after_construction(self) -> None:
        window = MarketWindow.build(make_series(T, [100.0, 101.0, 999.0]), T + 60)
        assert 999.0 not in window.closes()
        assert all(candle.close_time <= window.as_of for candle in window.candles)

    def test_a_candle_closing_exactly_at_as_of_is_visible(self) -> None:
        window = MarketWindow.build(make_series(T, [100.0]), T + 60)
        assert window.latest_close == 100.0

    def test_sorts_unordered_input(self) -> None:
        candles = list(reversed(make_series(T, [100.0, 101.0, 102.0])))
        window = MarketWindow.build(candles, T + 180)
        assert [c.open_time for c in window.candles] == [T, T + 60, T + 120]

    def test_empty_window_is_falsy_and_refuses_a_price(self) -> None:
        window = MarketWindow.build(make_series(T, [100.0]), T)
        assert not window
        with pytest.raises(InsufficientMarketDataError):
            _ = window.latest


class TestPriceAt:
    def test_returns_the_last_close_at_or_before_the_instant(self) -> None:
        candles = make_series(T, [100.0, 101.0, 102.0])
        assert price_at(candles, T + 180, max_staleness_seconds=120) == 102.0

    def test_never_uses_a_later_candle(self) -> None:
        candles = make_series(T, [100.0, 500.0])
        assert price_at(candles, T + 60, max_staleness_seconds=120) == 100.0

    def test_stale_data_fails_explicitly(self) -> None:
        candles = make_series(T, [100.0])
        with pytest.raises(StaleMarketDataError, match="tolerance"):
            price_at(candles, T + 3600, max_staleness_seconds=120)

    def test_no_data_fails_explicitly(self) -> None:
        with pytest.raises(InsufficientMarketDataError):
            price_at([], T, max_staleness_seconds=120)


class TestRealizedVolatility:
    def test_a_flat_series_has_zero_volatility(self) -> None:
        assert realized_volatility([100.0, 100.0, 100.0, 100.0]) == pytest.approx(0.0)

    def test_a_choppier_series_has_higher_volatility(self) -> None:
        calm = realized_volatility([100.0, 100.1, 100.0, 100.1, 100.0])
        wild = realized_volatility([100.0, 105.0, 98.0, 106.0, 97.0])
        assert wild > calm

    def test_matches_the_stdev_of_simple_returns(self) -> None:
        import statistics
        from itertools import pairwise

        prices = [100.0, 102.0, 101.0, 104.0]
        expected = statistics.stdev([(b - a) / a for a, b in pairwise(prices)])
        assert realized_volatility(prices) == pytest.approx(expected)

    def test_too_few_prices_fails_explicitly(self) -> None:
        with pytest.raises(InsufficientMarketDataError, match="at least 3"):
            realized_volatility([100.0, 101.0])


class TestResolutionEngine:
    def test_resolves_the_architecture_worked_example(self) -> None:
        # §14: reference 4500 at T, price 4545 at T+horizon -> +1% UP. The 4545 print
        # must belong to the candle that *closes* at T+900, i.e. the one opening at T+840.
        candles = make_series(T, [4500.0] * 14 + [4545.0])
        engine = ResolutionEngine(_SeriesProvider(candles))
        resolution = engine.resolve(make_task(4500.0))

        assert resolution.resolution_price == pytest.approx(4545.0)
        assert resolution.realized_return == pytest.approx(0.01)
        assert resolution.direction is Direction.UP

    def test_reference_price_is_the_price_at_task_time(self) -> None:
        candles = make_series(T - 600, [4400.0, 4450.0, 4500.0])
        engine = ResolutionEngine(_SeriesProvider(candles))
        assert engine.reference_price("ETH-USD", T - 600 + 180) == pytest.approx(4500.0)

    def test_resolution_keeps_the_reference_price_fixed_at_task_creation(self) -> None:
        # The recorded reference must never be refetched, or the realized return would
        # measure a different move than the miners were asked about.
        candles = make_series(T, [9999.0] * 15 + [4545.0])
        engine = ResolutionEngine(_SeriesProvider(candles))
        resolution = engine.resolve(make_task(4500.0))
        assert resolution.reference_price == 4500.0

    def test_a_flat_market_resolves_void(self) -> None:
        candles = make_series(T, [4500.0] * 16)
        engine = ResolutionEngine(_SeriesProvider(candles))
        resolution = engine.resolve(make_task(4500.0))
        assert resolution.is_void
        assert resolution.direction is None

    def test_missing_resolution_data_fails_explicitly(self) -> None:
        # Nothing at all near the resolution instant.
        engine = ResolutionEngine(_SeriesProvider(make_series(T, [4500.0])))
        with pytest.raises(InsufficientMarketDataError, match="no candles closed"):
            engine.resolve(make_task(4500.0))

    def test_a_venue_gap_before_resolution_is_stale_not_silently_priced(self) -> None:
        # Candles exist inside the lookback window but stop 300s before resolution, well
        # past the 2-interval tolerance. Resolving against that price would score every
        # miner on the wrong move, so it must fail loudly.
        engine = ResolutionEngine(_SeriesProvider(make_series(T + 540, [4500.0])))
        with pytest.raises(StaleMarketDataError, match="tolerance"):
            engine.resolve(make_task(4500.0))

    def test_return_scale_is_derived_from_observed_volatility(self) -> None:
        # A deterministic zig-zag: every 15m step alternates +1% / -1%.
        closes: list[float] = []
        price = 4000.0
        for index in range(40 * 15):
            if index % 15 == 0:
                price = price * (1.01 if (index // 15) % 2 == 0 else 0.99)
            closes.append(price)
        engine = ResolutionEngine(_SeriesProvider(make_series(T, closes)), min_volatility_samples=5)

        scale = engine.return_scale("ETH-USD", T + len(closes) * 60, HORIZON)

        assert 0.0 < scale < 0.05
        assert scale == pytest.approx(0.01, abs=0.005)

    def test_a_more_volatile_market_yields_a_larger_scale(self) -> None:
        def scale_for(step: float) -> float:
            closes: list[float] = []
            price = 4000.0
            for index in range(40 * 15):
                if index % 15 == 0:
                    price = price * (1 + step if (index // 15) % 2 == 0 else 1 - step)
                closes.append(price)
            engine = ResolutionEngine(
                _SeriesProvider(make_series(T, closes)), min_volatility_samples=5
            )
            return engine.return_scale("ETH-USD", T + len(closes) * 60, HORIZON)

        assert scale_for(0.02) > scale_for(0.002)

    def test_return_scale_never_looks_past_as_of(self) -> None:
        calm = [4000.0] * (40 * 15)
        spike = [40_000.0] * 100
        engine = ResolutionEngine(
            _SeriesProvider(make_series(T, calm + spike)), min_volatility_samples=5
        )
        as_of = T + len(calm) * 60
        with pytest.raises(InsufficientMarketDataError, match="volatility"):
            # The post-as_of spike is invisible, so the visible window is perfectly flat.
            engine.return_scale("ETH-USD", as_of, HORIZON)

    def test_flat_market_scale_fails_rather_than_returning_zero(self) -> None:
        engine = ResolutionEngine(
            _SeriesProvider(make_series(T, [4000.0] * (40 * 15))), min_volatility_samples=5
        )
        with pytest.raises(InsufficientMarketDataError):
            engine.return_scale("ETH-USD", T + 40 * 15 * 60, HORIZON)

    def test_too_little_history_fails_explicitly(self) -> None:
        engine = ResolutionEngine(_SeriesProvider(make_series(T, [4000.0, 4010.0, 4020.0])))
        with pytest.raises(InsufficientMarketDataError, match="horizon returns"):
            engine.return_scale("ETH-USD", T + 180, HORIZON)

    def test_horizon_must_be_a_multiple_of_the_candle_interval(self) -> None:
        engine = ResolutionEngine(_SeriesProvider([]))
        with pytest.raises(ValueError, match="multiple of 60"):
            engine.return_scale("ETH-USD", T, 90)

    def test_rejects_an_invalid_interval(self) -> None:
        with pytest.raises(ValueError, match="candle_interval_seconds"):
            ResolutionEngine(_SeriesProvider([]), candle_interval_seconds=0)


def test_price_lookup_rejects_a_non_finite_candle_close() -> None:
    with pytest.raises(Exception):  # noqa: B017 - malformed candle cannot be constructed
        make_candle(T, math.nan)
