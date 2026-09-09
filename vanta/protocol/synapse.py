"""The ForecastSynapse wire schema (ARCHITECTURE.md §6).

§6 defines the validator/miner exchange as a JSON request/response pair. Under
bittensor v10 that pair would have been carried by a ``bt.Synapse`` object; v11 removed
the axon/dendrite/synapse networking stack entirely, so subnets carry their own HTTP
layer and authenticate it with ``bittensor.http_auth``. The schema below *is* the
ForecastSynapse — the same fields §6 specifies, now as an explicit request and response
body rather than one bidirectional object.

This module deliberately imports no chain code. It is the boundary between untrusted
wire bytes and the domain models in :mod:`vanta.protocol.forecast`: every conversion
back into the mechanism runs the domain validators, so a malformed or hostile miner
response is rejected here rather than reaching the scorer.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from vanta.protocol.forecast import Forecast, ForecastTask
from vanta.validation import VantaValidationError

__all__ = [
    "FORECAST_PATH",
    "PROTOCOL_VERSION",
    "TASK_TYPE",
    "ForecastRequest",
    "ForecastResponse",
    "forecast_to_response",
    "parse_response",
    "request_to_task",
    "response_to_forecast",
    "task_to_request",
]

# The miner's HTTP endpoint. Part of the protocol: it is covered by the btauth signature,
# so validator and miner must agree on it exactly.
FORECAST_PATH = "/forecast"

# Bumped only when the wire schema changes incompatibly.
PROTOCOL_VERSION = 1

# §6's task_type. The MVP issues exactly one kind of task.
TASK_TYPE = "direction_return"


class ForecastRequest(BaseModel):
    """Validator -> miner. The task, exactly as §6 specifies it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    reference_price: float = Field(gt=0.0)
    timestamp: int = Field(ge=0)
    horizon_seconds: int = Field(gt=0)
    task_type: str = TASK_TYPE
    deadline: int = Field(ge=0)


class ForecastResponse(BaseModel):
    """Miner -> validator.

    ``probability_up`` and ``expected_return`` are the only required outputs (§6); the
    rest are optional and carried through untouched when present.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1)
    probability_up: float = Field(ge=0.0, le=1.0)
    expected_return: float
    expected_volatility: float | None = Field(default=None, ge=0.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    model_version: str | None = None


def task_to_request(task: ForecastTask) -> ForecastRequest:
    """Render a domain task as the outbound request body."""
    return ForecastRequest(
        task_id=task.task_id,
        asset=task.asset,
        reference_price=task.reference_price,
        timestamp=task.timestamp,
        horizon_seconds=task.horizon_seconds,
        task_type=TASK_TYPE,
        deadline=task.deadline,
    )


def request_to_task(request: ForecastRequest) -> ForecastTask:
    """Rebuild the domain task on the miner side.

    ``ForecastTask.__post_init__`` re-checks every invariant — notably that the
    submission deadline falls strictly before the resolution time (§27, §29) — so a
    validator cannot induce a miner to forecast a window it could already observe.
    """
    return ForecastTask(
        task_id=request.task_id,
        asset=request.asset,
        reference_price=request.reference_price,
        timestamp=request.timestamp,
        horizon_seconds=request.horizon_seconds,
        deadline=request.deadline,
    )


def response_to_forecast(response: ForecastResponse, *, miner_uid: int) -> Forecast:
    """Convert a miner's response into a scoreable :class:`Forecast`.

    Raises:
        VantaValidationError: if the response does not answer the task it claims to, or
            any field violates a mechanism invariant.
    """
    return Forecast(
        task_id=response.task_id,
        miner_uid=miner_uid,
        probability_up=response.probability_up,
        expected_return=response.expected_return,
        expected_volatility=response.expected_volatility,
        confidence=response.confidence,
        model_version=response.model_version,
    )


def forecast_to_response(forecast: Forecast) -> ForecastResponse:
    """Render a miner's own forecast as the outbound response body."""
    return ForecastResponse(
        task_id=forecast.task_id,
        probability_up=forecast.probability_up,
        expected_return=forecast.expected_return,
        expected_volatility=forecast.expected_volatility,
        confidence=forecast.confidence,
        model_version=forecast.model_version,
    )


def parse_response(payload: object, *, task_id: str, miner_uid: int) -> Forecast:
    """Parse an untrusted miner payload into a scoreable forecast.

    The one entry point the collector uses. It enforces that the response answers the
    task that was actually asked — a miner replying with another task's id would
    otherwise have its forecast scored against the wrong outcome.

    Raises:
        VantaValidationError: on any malformed, mismatched or invalid payload.
    """
    try:
        response = ForecastResponse.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError, or a non-mapping payload
        raise VantaValidationError(f"malformed forecast response: {exc}") from exc

    if response.task_id != task_id:
        raise VantaValidationError(
            f"response answers task {response.task_id!r}, expected {task_id!r}"
        )
    return response_to_forecast(response, miner_uid=miner_uid)
