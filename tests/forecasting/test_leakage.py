"""The leakage boundary (ARCHITECTURE.md §29).

These are the most important tests in the package. If an engine can see past ``T``, every
score it earns is meaningless.
"""

from __future__ import annotations

import pytest

from tests.forecasting.helpers import (
    INTERVAL,
    T,
    candles_from,
    context_ending_at,
    make_task,
    trend,
)
from vanta.forecasting import default_engines
from vanta.forecasting.base import ForecastContext
from vanta.market.errors import InsufficientMarketDataError, LookaheadError
from vanta.market.provider import Candle
from vanta.market.resolution import MarketWindow


class TestStructuralBoundary:
    def test_building_a_context_drops_candles_after_task_time(self) -> None:
        closes = trend(120)
        start = T - 100 * INTERVAL
        candles = candles_from(closes, start=start)
        context = ForecastContext.build(make_task(), candles)
        assert all(candle.close_time <= T for candle in context.history.candles)

    def test_a_window_cannot_be_handed_future_data_directly(self) -> None:
        # The guarantee must not depend on going through `build`.
        future = Candle(
            open_time=T,
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
            volume=1.0,
            interval_seconds=INTERVAL,
        )
        with pytest.raises(LookaheadError, match="cannot hold future data"):
            MarketWindow(as_of=T, candles=(future,))

    def test_a_context_cannot_be_pinned_to_a_different_instant(self) -> None:
        window = MarketWindow.build(candles_from(trend(50), start=T - 100 * INTERVAL), T - 600)
        with pytest.raises(InsufficientMarketDataError, match="pinned to"):
            ForecastContext(task=make_task(), history=window)

    def test_window_rejects_unordered_candles(self) -> None:
        candles = candles_from(trend(3), start=T - 10 * INTERVAL)
        with pytest.raises(LookaheadError, match="ascending"):
            MarketWindow(as_of=T, candles=tuple(reversed(candles)))


@pytest.mark.parametrize("engine", default_engines(), ids=lambda e: e.name)
class TestFutureDataCannotChangeAForecast:
    def test_appending_future_candles_changes_nothing(self, engine) -> None:
        closes = trend(300)
        start = T - 250 * INTERVAL
        visible = candles_from(closes, start=start)

        before = engine.forecast(ForecastContext.build(make_task(), visible), miner_uid=1)

        # A violent post-T move that would obviously alter any forecast that could see it.
        after_t = candles_from([closes[-1] * 3.0] * 50, start=visible[-1].open_time + INTERVAL)
        after = engine.forecast(
            ForecastContext.build(make_task(), [*visible, *after_t]), miner_uid=1
        )

        assert before.probability_up == after.probability_up
        assert before.expected_return == after.expected_return

    def test_modifying_future_candles_changes_nothing(self, engine) -> None:
        closes = trend(300)
        start = T - 250 * INTERVAL
        visible = candles_from(closes, start=start)
        tail_start = visible[-1].open_time + INTERVAL

        crash = engine.forecast(
            ForecastContext.build(
                make_task(), [*visible, *candles_from([1.0] * 20, start=tail_start)]
            ),
            miner_uid=1,
        )
        moon = engine.forecast(
            ForecastContext.build(
                make_task(), [*visible, *candles_from([99_999.0] * 20, start=tail_start)]
            ),
            miner_uid=1,
        )

        assert crash.probability_up == moon.probability_up
        assert crash.expected_return == moon.expected_return

    def test_a_candle_still_forming_at_t_is_invisible(self, engine) -> None:
        # A candle opening at T-30 closes at T+30 and its close is not yet knowable.
        closes = trend(300)
        start = T - 250 * INTERVAL
        visible = candles_from(closes, start=start)
        forming = Candle(
            open_time=T - 30,
            open=closes[-1],
            high=closes[-1] * 5,
            low=closes[-1],
            close=closes[-1] * 5,
            volume=1.0,
            interval_seconds=INTERVAL,
        )
        assert engine.forecast(
            ForecastContext.build(make_task(), visible), miner_uid=1
        ) == engine.forecast(ForecastContext.build(make_task(), [*visible, forming]), miner_uid=1)


def test_ml_training_labels_never_reach_past_the_window() -> None:
    # The ML engine is the only one that builds labels from future-relative prices, so it
    # is the one that could leak. Its training set must stop one horizon short of T.
    from vanta.forecasting.ml import MLEngine

    engine = MLEngine()
    context = context_ending_at(trend(400))
    closes = context.closes
    rows, directions, returns = engine._training_set(closes, context.horizon_steps)

    assert len(rows) == len(directions) == len(returns)
    # The newest labelled sample sits a full horizon behind the visible edge.
    assert len(rows) == len(closes) - context.horizon_steps - 21
