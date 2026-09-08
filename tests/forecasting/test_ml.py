from __future__ import annotations

import math

import pytest

from tests.forecasting.helpers import context_ending_at, flat, trend
from vanta.forecasting.ml import MLEngine
from vanta.market.errors import InsufficientMarketDataError

RISING = trend(400, step=0.0008)
FALLING = trend(400, step=-0.0008)


class TestTraining:
    def test_is_deterministic_across_fits(self) -> None:
        # Zero initialization and a fixed epoch count mean there is no random state.
        context = context_ending_at(RISING)
        assert MLEngine().predict(context) == MLEngine().predict(context)

    def test_produces_a_valid_forecast(self) -> None:
        prediction = MLEngine().predict(context_ending_at(RISING))
        assert 0.0 <= prediction.probability_up <= 1.0
        assert math.isfinite(prediction.expected_return)

    def test_learns_direction_from_a_persistently_rising_market(self) -> None:
        # Every horizon in this series closes higher, so the fitted model should be bullish.
        assert MLEngine().predict(context_ending_at(RISING)).probability_up > 0.5

    def test_learns_direction_from_a_persistently_falling_market(self) -> None:
        assert MLEngine().predict(context_ending_at(FALLING)).probability_up < 0.5

    def test_expected_return_follows_the_fitted_sign(self) -> None:
        assert MLEngine().predict(context_ending_at(RISING)).expected_return > 0.0
        assert MLEngine().predict(context_ending_at(FALLING)).expected_return < 0.0

    def test_more_epochs_sharpen_a_learnable_signal(self) -> None:
        context = context_ending_at(RISING)
        brief = MLEngine(epochs=5).predict(context)
        trained = MLEngine(epochs=300).predict(context)
        assert trained.probability_up > brief.probability_up

    def test_labels_are_balanced_on_an_oscillating_series(self) -> None:
        engine = MLEngine()
        context = context_ending_at([4000.0 * (1.0 + 0.01 * math.sin(i / 7.0)) for i in range(400)])
        _, directions, _ = engine._training_set(context.closes, context.horizon_steps)
        share_up = sum(directions) / len(directions)
        assert 0.2 < share_up < 0.8


class TestExplicitFailures:
    def test_history_requirement_grows_with_the_horizon(self) -> None:
        engine = MLEngine()
        short = context_ending_at(flat(400), horizon=900)
        long = context_ending_at(flat(400), horizon=3600)
        assert engine.required_history(long) > engine.required_history(short)

    def test_insufficient_history_fails_explicitly(self) -> None:
        with pytest.raises(InsufficientMarketDataError, match="needs"):
            MLEngine().forecast(context_ending_at(flat(40)), miner_uid=1)

    def test_too_few_training_samples_fails_explicitly(self) -> None:
        engine = MLEngine(min_samples=500)
        with pytest.raises(InsufficientMarketDataError):
            engine.forecast(context_ending_at(RISING), miner_uid=1)

    def test_a_flat_market_does_not_produce_nan(self) -> None:
        # Every feature column is constant, so standardization must not divide by zero.
        prediction = MLEngine().predict(context_ending_at(flat(400)))
        assert math.isfinite(prediction.probability_up)
        assert math.isfinite(prediction.expected_return)


def test_uses_no_third_party_machine_learning_dependency() -> None:
    import vanta.forecasting.ml as module

    source = module.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    for banned in ("sklearn", "scikit", "numpy", "torch", "tensorflow"):
        assert f"import {banned}" not in text
