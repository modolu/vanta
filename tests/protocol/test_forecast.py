from __future__ import annotations

import math

import pytest

from vanta.protocol.forecast import (
    Direction,
    Forecast,
    ForecastTask,
    Resolution,
    VoidResolutionError,
)
from vanta.validation import VantaValidationError

T = 1_789_905_600
HORIZON = 900


def make_task(**overrides: object) -> ForecastTask:
    kwargs: dict[str, object] = {
        "task_id": "eth-15m-1",
        "asset": "ETH-USD",
        "reference_price": 4500.0,
        "timestamp": T,
        "horizon_seconds": HORIZON,
        "deadline": T + 30,
    }
    kwargs.update(overrides)
    return ForecastTask(**kwargs)  # type: ignore[arg-type]


class TestForecastTask:
    def test_resolve_at_is_timestamp_plus_horizon(self) -> None:
        assert make_task().resolve_at == T + HORIZON

    def test_deadline_must_follow_the_task_timestamp(self) -> None:
        with pytest.raises(VantaValidationError, match="must be after task timestamp"):
            make_task(deadline=T)

    def test_deadline_may_not_reach_the_resolution_time(self) -> None:
        # A submission window extending to resolution would leak the outcome (§27, §29).
        with pytest.raises(VantaValidationError, match="before resolution time"):
            make_task(deadline=T + HORIZON)

    def test_reference_price_must_be_positive(self) -> None:
        with pytest.raises(VantaValidationError, match="reference_price"):
            make_task(reference_price=0.0)

    def test_horizon_must_be_positive(self) -> None:
        with pytest.raises(VantaValidationError, match="horizon_seconds"):
            make_task(horizon_seconds=0)

    def test_task_id_must_be_a_non_empty_string(self) -> None:
        with pytest.raises(VantaValidationError, match="task_id"):
            make_task(task_id="   ")

    def test_is_immutable(self) -> None:
        with pytest.raises((AttributeError, TypeError)):
            make_task().reference_price = 1.0  # type: ignore[misc]


class TestForecast:
    def test_only_probability_and_return_are_required(self) -> None:
        forecast = Forecast(
            task_id="eth-15m-1", miner_uid=7, probability_up=0.67, expected_return=0.0041
        )
        assert forecast.expected_volatility is None
        assert forecast.confidence is None
        assert forecast.model_version is None

    def test_probability_down_is_the_complement(self) -> None:
        forecast = Forecast(task_id="t", miner_uid=0, probability_up=0.25, expected_return=0.0)
        assert forecast.probability_down == pytest.approx(0.75)

    @pytest.mark.parametrize("bad", [-0.01, 1.01, math.nan, math.inf])
    def test_invalid_probabilities_are_rejected(self, bad: float) -> None:
        with pytest.raises(VantaValidationError, match="probability_up"):
            Forecast(task_id="t", miner_uid=0, probability_up=bad, expected_return=0.0)

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_non_finite_expected_return_is_rejected(self, bad: float) -> None:
        with pytest.raises(VantaValidationError, match="expected_return"):
            Forecast(task_id="t", miner_uid=0, probability_up=0.5, expected_return=bad)

    def test_negative_miner_uid_is_rejected(self) -> None:
        with pytest.raises(VantaValidationError, match="miner_uid"):
            Forecast(task_id="t", miner_uid=-1, probability_up=0.5, expected_return=0.0)

    def test_optional_fields_are_validated_when_supplied(self) -> None:
        with pytest.raises(VantaValidationError, match="expected_volatility"):
            Forecast(
                task_id="t",
                miner_uid=0,
                probability_up=0.5,
                expected_return=0.0,
                expected_volatility=-0.01,
            )
        with pytest.raises(VantaValidationError, match="confidence"):
            Forecast(
                task_id="t", miner_uid=0, probability_up=0.5, expected_return=0.0, confidence=1.5
            )


class TestResolution:
    def test_realized_return_and_direction_match_the_worked_example(self) -> None:
        # §14: reference 4500, resolution 4545 -> +1% UP.
        resolution = Resolution.from_task(
            make_task(reference_price=4500.0), resolution_price=4545.0
        )
        assert resolution.realized_return == pytest.approx(0.01)
        assert resolution.direction is Direction.UP
        assert resolution.outcome == 1.0

    def test_a_falling_market_resolves_down(self) -> None:
        resolution = Resolution.from_task(make_task(), resolution_price=4455.0)
        assert resolution.realized_return == pytest.approx(-0.01)
        assert resolution.direction is Direction.DOWN
        assert resolution.outcome == 0.0

    def test_flat_market_voids_the_directional_outcome(self) -> None:
        # LOCKED (§14): exactly flat voids direction rather than counting as DOWN.
        resolution = Resolution.from_task(make_task(), resolution_price=4500.0)
        assert resolution.realized_return == 0.0
        assert resolution.is_void
        assert resolution.direction is None
        assert resolution.outcome is None

    def test_void_resolution_refuses_to_produce_an_outcome(self) -> None:
        resolution = Resolution.from_task(make_task(), resolution_price=4500.0)
        with pytest.raises(VoidResolutionError, match="no directional outcome"):
            resolution.require_outcome()

    def test_non_flat_resolutions_are_not_void(self) -> None:
        for price in (4500.01, 4499.99):
            resolution = Resolution.from_task(make_task(), resolution_price=price)
            assert not resolution.is_void
            assert resolution.direction is not None
            assert resolution.require_outcome() == resolution.outcome

    def test_from_task_inherits_reference_price_and_resolution_time(self) -> None:
        task = make_task()
        resolution = Resolution.from_task(task, resolution_price=4600.0)
        assert resolution.reference_price == task.reference_price
        assert resolution.resolved_at == task.resolve_at
        assert resolution.task_id == task.task_id

    def test_prices_must_be_positive(self) -> None:
        with pytest.raises(VantaValidationError, match="resolution_price"):
            Resolution(task_id="t", reference_price=4500.0, resolution_price=0.0, resolved_at=T)


def test_direction_outcome_mapping() -> None:
    assert Direction.UP.outcome == 1.0
    assert Direction.DOWN.outcome == 0.0
