from __future__ import annotations

import math

import pytest

from tests.forecasting.helpers import HORIZON, INTERVAL, context_ending_at, flat, make_task
from vanta.forecasting.base import ForecastContext, ForecastEngine, Prediction
from vanta.market.errors import InsufficientMarketDataError
from vanta.validation import VantaValidationError


class TestPrediction:
    def test_clamps_floating_point_overshoot(self) -> None:
        assert Prediction(probability_up=1.0 + 1e-16, expected_return=0.0).probability_up == 1.0
        assert Prediction(probability_up=-1e-16, expected_return=0.0).probability_up == 0.0

    def test_keeps_valid_probabilities_untouched(self) -> None:
        assert Prediction(probability_up=0.67, expected_return=0.004).probability_up == 0.67

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_non_finite_probability_is_a_bug_not_a_rounding_artifact(self, bad: float) -> None:
        with pytest.raises(VantaValidationError, match="probability_up"):
            Prediction(probability_up=bad, expected_return=0.0)

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_non_finite_expected_return_is_rejected(self, bad: float) -> None:
        with pytest.raises(VantaValidationError, match="expected_return"):
            Prediction(probability_up=0.5, expected_return=bad)


class TestForecastContext:
    def test_exposes_visible_closes_oldest_first(self) -> None:
        context = context_ending_at([100.0, 101.0, 102.0])
        assert context.closes == (100.0, 101.0, 102.0)

    def test_reports_the_candle_interval_and_horizon_in_steps(self) -> None:
        context = context_ending_at(flat(50))
        assert context.interval_seconds == INTERVAL
        assert context.horizon_steps == HORIZON // INTERVAL

    def test_a_horizon_that_is_not_a_whole_number_of_candles_fails(self) -> None:
        context = context_ending_at(flat(50), horizon=90)
        with pytest.raises(InsufficientMarketDataError, match="whole number"):
            _ = context.horizon_steps

    def test_reference_price_comes_from_the_task(self) -> None:
        task = make_task(reference_price=1234.5)
        context = ForecastContext.build(task, [])
        assert context.reference_price == 1234.5


class _NeedsHistory(ForecastEngine):
    name = "needs-history"
    min_history = 10

    def predict(self, context: ForecastContext) -> Prediction:  # pragma: no cover - not reached
        return Prediction(probability_up=0.5, expected_return=0.0)


class _Constant(ForecastEngine):
    name = "constant"

    def predict(self, context: ForecastContext) -> Prediction:
        return Prediction(probability_up=0.6, expected_return=0.001)


class TestForecastEngine:
    def test_insufficient_history_fails_explicitly(self) -> None:
        context = context_ending_at(flat(3))
        with pytest.raises(InsufficientMarketDataError, match="needs 10 candles"):
            _NeedsHistory().forecast(context, miner_uid=1)

    def test_assembles_a_protocol_forecast(self) -> None:
        context = context_ending_at(flat(30))
        forecast = _Constant().forecast(context, miner_uid=17)
        assert forecast.task_id == context.task.task_id
        assert forecast.miner_uid == 17
        assert forecast.probability_up == 0.6
        assert forecast.expected_return == 0.001
        assert forecast.model_version == "constant-v1"

    def test_engine_cannot_be_instantiated_without_predict(self) -> None:
        with pytest.raises(TypeError):
            ForecastEngine()  # type: ignore[abstract]
