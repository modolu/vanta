"""The miner neuron: handler, access control, and the structural leakage boundary."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vanta.forecasting import MomentumEngine, PersistenceEngine
from vanta.forecasting.base import ForecastContext, Prediction
from vanta.market.errors import InsufficientMarketDataError
from vanta.neurons.chain import ChainError
from vanta.neurons.miner import ForecastService, HotkeyGate, create_app
from vanta.protocol.synapse import FORECAST_PATH, ForecastRequest, task_to_request
from vanta.validation import VantaValidationError

from .helpers import (
    INTERVAL,
    FakeSubnetView,
    SeriesProvider,
    candles_from,
    drifting_closes,
    make_task,
    neuron,
)

T = 1_788_900_000


def service(*, closes: int = 300, engine=None, lookback: int = 200) -> ForecastService:
    series = candles_from(drifting_closes(closes), start=T - closes * INTERVAL)
    return ForecastService(
        engine=engine or MomentumEngine(),
        provider=SeriesProvider(series),
        candle_interval_seconds=INTERVAL,
        lookback_candles=lookback,
    )


class TestForecastService:
    def test_answers_a_well_formed_request(self) -> None:
        response = service().forecast(task_to_request(make_task(timestamp=T)))
        assert 0.0 <= response.probability_up <= 1.0
        assert response.model_version == "momentum-v1"

    def test_the_response_answers_the_task_it_was_asked(self) -> None:
        task = make_task(timestamp=T)
        assert service().forecast(task_to_request(task)).task_id == task.task_id

    def test_rejects_a_deadline_reaching_the_resolution_time(self) -> None:
        """§27/§29: the miner refuses a window it could already have observed."""
        request = ForecastRequest(
            task_id="t",
            asset="ETH-USD",
            reference_price=4500.0,
            timestamp=T,
            horizon_seconds=900,
            deadline=T + 900,
        )
        with pytest.raises(VantaValidationError):
            service().forecast(request)

    def test_raises_when_history_is_too_short(self) -> None:
        with pytest.raises(InsufficientMarketDataError):
            service(closes=3, lookback=3).forecast(task_to_request(make_task(timestamp=T)))

    @pytest.mark.parametrize("field", ["candle_interval_seconds", "lookback_candles"])
    def test_rejects_a_non_positive_configuration(self, field: str) -> None:
        with pytest.raises(ValueError):
            ForecastService(engine=MomentumEngine(), provider=SeriesProvider([]), **{field: 0})

    def test_the_engine_is_swappable_without_touching_neuron_code(self) -> None:
        """§10: replacing the forecast engine must not require neuron changes."""
        momentum = service(engine=MomentumEngine()).forecast(
            task_to_request(make_task(timestamp=T))
        )
        persistence = service(engine=PersistenceEngine()).forecast(
            task_to_request(make_task(timestamp=T))
        )
        assert momentum.model_version != persistence.model_version


class TestNoLookAhead:
    def test_the_engine_never_sees_data_past_the_task_instant(self) -> None:
        """§29: the outcome bar is structurally unreachable, not merely un-consulted."""
        seen: list[ForecastContext] = []

        class SpyEngine(MomentumEngine):
            def predict(self, context: ForecastContext) -> Prediction:
                seen.append(context)
                return super().predict(context)

        # The provider holds candles well past T, covering the whole horizon.
        closes = drifting_closes(400)
        provider = SeriesProvider(candles_from(closes, start=T - 300 * INTERVAL))
        handler = ForecastService(
            engine=SpyEngine(),
            provider=provider,
            candle_interval_seconds=INTERVAL,
            lookback_candles=200,
        )
        task = make_task(timestamp=T)
        handler.forecast(task_to_request(task))

        context = seen[0]
        assert context.history.as_of == T
        assert context.history.candles, "the engine must actually receive history"
        latest = max(candle.close_time for candle in context.history.candles)
        assert latest <= T
        assert latest < task.resolve_at

    def test_the_provider_is_never_asked_for_data_past_the_task_instant(self) -> None:
        handler = service()
        task = make_task(timestamp=T)
        handler.forecast(task_to_request(task))

        assert handler.provider.requests  # type: ignore[attr-defined]
        for _asset, _interval, _start, end in handler.provider.requests:  # type: ignore[attr-defined]
            assert end <= task.timestamp


class TestHotkeyGate:
    def test_an_open_gate_serves_everyone(self) -> None:
        gate = HotkeyGate(None, netuid=1)
        assert gate.is_open
        assert gate.allows("anyone")

    def test_only_registered_hotkeys_are_served(self) -> None:
        view = FakeSubnetView([neuron(0, "alice"), neuron(1, "bob")])
        gate = HotkeyGate(view, netuid=1)
        assert gate.allows("alice")
        assert not gate.allows("mallory")

    def test_a_minimum_stake_can_be_required(self) -> None:
        view = FakeSubnetView([neuron(0, "rich", stake=100.0), neuron(1, "poor", stake=0.5)])
        gate = HotkeyGate(view, netuid=1, min_stake=10.0)
        assert gate.allows("rich")
        assert not gate.allows("poor")

    def test_a_validator_permit_can_be_required(self) -> None:
        view = FakeSubnetView([neuron(0, "validator", validator_permit=True), neuron(1, "miner")])
        gate = HotkeyGate(view, netuid=1, require_validator_permit=True)
        assert gate.allows("validator")
        assert not gate.allows("miner")

    def test_the_set_is_cached_between_refreshes(self) -> None:
        view = FakeSubnetView([neuron(0, "alice")])
        clock = iter([0.0, 1.0, 2.0, 3.0])
        gate = HotkeyGate(view, netuid=1, refresh_seconds=300.0, clock=lambda: next(clock))
        gate.allows("alice")
        gate.allows("alice")
        assert view.calls == 1

    def test_refreshes_after_the_interval(self) -> None:
        view = FakeSubnetView([neuron(0, "alice")])
        now = [0.0]
        gate = HotkeyGate(view, netuid=1, refresh_seconds=10.0, clock=lambda: now[0])
        assert gate.allows("alice")
        assert not gate.allows("bob")

        view.set([neuron(0, "alice"), neuron(1, "bob")])
        now[0] = 100.0
        assert gate.allows("bob")

    def test_a_chain_failure_keeps_the_previous_set(self) -> None:
        """A transient read failure must not lock every validator out."""
        view = FakeSubnetView([neuron(0, "alice")])
        now = [0.0]
        gate = HotkeyGate(view, netuid=1, refresh_seconds=10.0, clock=lambda: now[0])
        assert gate.allows("alice")

        view.fail_with = "connection refused"
        now[0] = 100.0
        assert gate.allows("alice")

    def test_rejects_a_non_positive_refresh(self) -> None:
        with pytest.raises(ValueError):
            HotkeyGate(None, netuid=1, refresh_seconds=0.0)


class TestHttpEndpoint:
    def client(self, **kwargs) -> TestClient:
        return TestClient(create_app(service(), **kwargs))

    def test_health_reports_the_served_engine(self) -> None:
        body = self.client().get("/health").json()
        assert body["status"] == "ok"
        assert body["engine"] == "momentum"
        assert body["authenticated"] is False

    def test_serves_a_forecast(self) -> None:
        task = make_task(timestamp=T)
        response = self.client().post(
            FORECAST_PATH, content=task_to_request(task).model_dump_json()
        )
        assert response.status_code == 200
        body = response.json()
        assert body["task_id"] == task.task_id
        assert 0.0 <= body["probability_up"] <= 1.0

    def test_a_malformed_body_is_a_400(self) -> None:
        assert self.client().post(FORECAST_PATH, content=b"{not json").status_code == 400

    def test_a_protocol_violation_is_a_400(self) -> None:
        bad = ForecastRequest(
            task_id="t",
            asset="ETH-USD",
            reference_price=4500.0,
            timestamp=T,
            horizon_seconds=900,
            deadline=T + 900,
        )
        response = self.client().post(FORECAST_PATH, content=bad.model_dump_json())
        assert response.status_code == 400

    def test_missing_history_is_a_503(self) -> None:
        client = TestClient(create_app(service(closes=3, lookback=3)))
        response = client.post(
            FORECAST_PATH, content=task_to_request(make_task(timestamp=T)).model_dump_json()
        )
        assert response.status_code == 503

    def test_an_unauthenticated_caller_is_a_401(self) -> None:
        def verifier(*, headers, body, method, path):  # type: ignore[no-untyped-def]
            raise ChainError("missing X-Bittensor-Signature")

        client = TestClient(create_app(service(), verifier=verifier))
        response = client.post(
            FORECAST_PATH, content=task_to_request(make_task(timestamp=T)).model_dump_json()
        )
        assert response.status_code == 401

    def test_an_unregistered_caller_is_a_403(self) -> None:
        def verifier(*, headers, body, method, path):  # type: ignore[no-untyped-def]
            return "mallory"

        gate = HotkeyGate(FakeSubnetView([neuron(0, "alice")]), netuid=1)
        client = TestClient(create_app(service(), gate=gate, verifier=verifier))
        response = client.post(
            FORECAST_PATH, content=task_to_request(make_task(timestamp=T)).model_dump_json()
        )
        assert response.status_code == 403

    def test_an_authenticated_registered_caller_is_served(self) -> None:
        def verifier(*, headers, body, method, path):  # type: ignore[no-untyped-def]
            assert method == "POST"
            assert path == FORECAST_PATH
            return "alice"

        gate = HotkeyGate(FakeSubnetView([neuron(0, "alice")]), netuid=1)
        client = TestClient(create_app(service(), gate=gate, verifier=verifier))
        response = client.post(
            FORECAST_PATH, content=task_to_request(make_task(timestamp=T)).model_dump_json()
        )
        assert response.status_code == 200

    def test_the_verifier_receives_the_raw_body(self) -> None:
        """The signature covers the bytes as they arrived, before any parsing."""
        seen: dict[str, bytes] = {}

        def verifier(*, headers, body, method, path):  # type: ignore[no-untyped-def]
            seen["body"] = body
            return "alice"

        sent = task_to_request(make_task(timestamp=T)).model_dump_json().encode("utf-8")
        TestClient(create_app(service(), verifier=verifier)).post(FORECAST_PATH, content=sent)
        assert seen["body"] == sent
