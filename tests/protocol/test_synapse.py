"""The ForecastSynapse wire schema (§6) and its boundary validation."""

from __future__ import annotations

import pytest

from vanta.protocol.forecast import Forecast, ForecastTask
from vanta.protocol.synapse import (
    FORECAST_PATH,
    TASK_TYPE,
    ForecastRequest,
    ForecastResponse,
    forecast_to_response,
    parse_response,
    request_to_task,
    response_to_forecast,
    task_to_request,
)
from vanta.validation import VantaValidationError

T = 1_788_900_000


def make_task(**overrides: object) -> ForecastTask:
    values: dict[str, object] = {
        "task_id": "ETH-USD-900s-1788900000",
        "asset": "ETH-USD",
        "reference_price": 4512.40,
        "timestamp": T,
        "horizon_seconds": 900,
        "deadline": T + 30,
    }
    values.update(overrides)
    return ForecastTask(**values)  # type: ignore[arg-type]


class TestRequest:
    def test_round_trips_through_the_wire_and_back(self) -> None:
        task = make_task()
        rebuilt = request_to_task(task_to_request(task))
        assert rebuilt == task

    def test_survives_json_serialization(self) -> None:
        task = make_task()
        wire = task_to_request(task).model_dump_json()
        assert request_to_task(ForecastRequest.model_validate_json(wire)) == task

    def test_carries_the_section_6_task_type(self) -> None:
        assert task_to_request(make_task()).task_type == TASK_TYPE

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValueError):
            ForecastRequest.model_validate(
                {
                    "task_id": "t",
                    "asset": "ETH-USD",
                    "reference_price": 1.0,
                    "timestamp": T,
                    "horizon_seconds": 900,
                    "deadline": T + 30,
                    "surprise": 1,
                }
            )

    def test_rejects_a_non_positive_reference_price(self) -> None:
        with pytest.raises(ValueError):
            ForecastRequest.model_validate(
                {
                    "task_id": "t",
                    "asset": "ETH-USD",
                    "reference_price": 0.0,
                    "timestamp": T,
                    "horizon_seconds": 900,
                    "deadline": T + 30,
                }
            )

    def test_a_deadline_at_resolution_is_rejected_when_rebuilt(self) -> None:
        """§27/§29: the miner rebuilds the task and refuses a window reaching resolution.

        The wire schema alone cannot express this rule; the domain model enforces it, so
        a validator cannot induce a miner to forecast an already-observable window.
        """
        request = ForecastRequest(
            task_id="t",
            asset="ETH-USD",
            reference_price=4500.0,
            timestamp=T,
            horizon_seconds=900,
            deadline=T + 900,
        )
        with pytest.raises(VantaValidationError, match="must fall before resolution time"):
            request_to_task(request)


class TestResponse:
    def test_requires_only_the_two_mandatory_outputs(self) -> None:
        """§6: probability_up and expected_return; everything else optional."""
        response = ForecastResponse.model_validate(
            {"task_id": "t", "probability_up": 0.67, "expected_return": 0.0041}
        )
        assert response.expected_volatility is None
        assert response.confidence is None
        assert response.model_version is None

    def test_carries_the_optional_fields_when_present(self) -> None:
        forecast = Forecast(
            task_id="t",
            miner_uid=3,
            probability_up=0.67,
            expected_return=0.0041,
            expected_volatility=0.0089,
            confidence=0.73,
            model_version="v3.1",
        )
        response = forecast_to_response(forecast)
        assert response.expected_volatility == pytest.approx(0.0089)
        assert response.confidence == pytest.approx(0.73)
        assert response.model_version == "v3.1"
        assert response_to_forecast(response, miner_uid=3) == forecast

    @pytest.mark.parametrize("probability", [-0.01, 1.01])
    def test_rejects_a_probability_outside_the_unit_interval(self, probability: float) -> None:
        with pytest.raises(ValueError):
            ForecastResponse.model_validate(
                {"task_id": "t", "probability_up": probability, "expected_return": 0.0}
            )

    @pytest.mark.parametrize("value", [float("nan"), float("inf")])
    def test_rejects_non_finite_numbers_at_the_domain_boundary(self, value: float) -> None:
        response = ForecastResponse.model_construct(
            task_id="t", probability_up=0.5, expected_return=value
        )
        with pytest.raises(VantaValidationError):
            response_to_forecast(response, miner_uid=0)


class TestParseResponse:
    def test_parses_a_well_formed_payload(self) -> None:
        forecast = parse_response(
            {"task_id": "t", "probability_up": 0.6, "expected_return": 0.001},
            task_id="t",
            miner_uid=7,
        )
        assert forecast.miner_uid == 7
        assert forecast.probability_up == pytest.approx(0.6)

    def test_rejects_a_response_answering_a_different_task(self) -> None:
        """A miner must not be scored against an outcome it was not asked about."""
        with pytest.raises(VantaValidationError, match="answers task"):
            parse_response(
                {"task_id": "other", "probability_up": 0.6, "expected_return": 0.001},
                task_id="t",
                miner_uid=0,
            )

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            "not-a-mapping",
            {},
            {"task_id": "t", "probability_up": 0.6},
            {"task_id": "t", "probability_up": "high", "expected_return": 0.0},
            {"task_id": "t", "probability_up": 2.0, "expected_return": 0.0},
        ],
    )
    def test_rejects_malformed_payloads(self, payload: object) -> None:
        with pytest.raises(VantaValidationError):
            parse_response(payload, task_id="t", miner_uid=0)


def test_forecast_path_is_stable() -> None:
    """The path is covered by the btauth signature; changing it breaks every miner."""
    assert FORECAST_PATH == "/forecast"
