"""Miner fan-out and response collection (§7, §27).

Every test runs against a scripted transport; nothing opens a socket.
"""

from __future__ import annotations

import json

import pytest

from vanta.protocol.synapse import FORECAST_PATH, ForecastRequest
from vanta.validator.collector import ForecastCollector, MinerQuery, TransportReply

from ..neurons.helpers import ScriptedTransport, make_task

T = 1_788_900_000


def reply(task_id: str, probability: float = 0.6, expected_return: float = 0.001) -> dict:
    return {
        "task_id": task_id,
        "probability_up": probability,
        "expected_return": expected_return,
    }


def miners(count: int = 3) -> list[MinerQuery]:
    return [
        MinerQuery(uid=uid, hotkey=f"hot{uid}", url=f"http://127.0.0.1:{9000 + uid}")
        for uid in range(count)
    ]


def collector(transport: ScriptedTransport, **kwargs: object) -> ForecastCollector:
    kwargs.setdefault("clock", lambda: float(T))
    return ForecastCollector(transport, **kwargs)  # type: ignore[arg-type]


class TestHappyPath:
    def test_collects_every_valid_on_time_response(self) -> None:
        task = make_task(timestamp=T)
        transport = ScriptedTransport(
            {uid: reply(task.task_id) for uid in range(3)}, received_at=float(T + 1)
        )
        result = collector(transport).collect(task, miners())

        assert set(result.forecasts) == {0, 1, 2}
        assert result.rejected == {}
        assert result.responded == 3

    def test_sends_the_task_as_the_section_6_request_body(self) -> None:
        task = make_task(timestamp=T)
        transport = ScriptedTransport({0: reply(task.task_id)}, received_at=float(T + 1))
        collector(transport).collect(task, miners(1))

        url, body, headers = transport.calls[0]
        assert url.endswith(FORECAST_PATH)
        assert headers["content-type"] == "application/json"
        sent = ForecastRequest.model_validate(json.loads(body))
        assert sent.task_id == task.task_id
        assert sent.reference_price == pytest.approx(task.reference_price)
        assert sent.deadline == task.deadline

    def test_records_the_hotkey_behind_every_uid(self) -> None:
        task = make_task(timestamp=T)
        transport = ScriptedTransport({0: reply(task.task_id)}, received_at=float(T + 1))
        result = collector(transport).collect(task, miners(2))
        assert result.hotkeys == {0: "hot0", 1: "hot1"}


class TestDeadline:
    def test_a_late_response_is_discarded(self) -> None:
        """§27: waiting for more market movement must not pay."""
        task = make_task(timestamp=T)
        transport = ScriptedTransport(
            {0: reply(task.task_id), 1: reply(task.task_id)},
            late=[1],
            received_at=float(T + 1),
        )
        result = collector(transport).collect(task, miners(2))

        assert set(result.forecasts) == {0}
        assert "late" in result.rejected[1]

    def test_a_response_exactly_on_the_deadline_is_accepted(self) -> None:
        task = make_task(timestamp=T)
        transport = ScriptedTransport({0: reply(task.task_id)}, received_at=float(task.deadline))
        result = collector(transport).collect(task, miners(1))
        assert set(result.forecasts) == {0}

    def test_nothing_is_queried_once_the_deadline_has_passed(self) -> None:
        task = make_task(timestamp=T)
        transport = ScriptedTransport({0: reply(task.task_id)})
        result = ForecastCollector(transport, clock=lambda: float(task.deadline + 1)).collect(
            task, miners(1)
        )
        assert result.forecasts == {}
        assert "deadline had already passed" in result.rejected[0]
        assert transport.calls == []

    def test_the_timeout_never_outlives_the_submission_window(self) -> None:
        task = make_task(timestamp=T)
        captured: dict[str, float] = {}

        class Recording(ScriptedTransport):
            def post_all(self, calls, *, timeout):  # type: ignore[no-untyped-def]
                captured["timeout"] = timeout
                return super().post_all(calls, timeout=timeout)

        transport = Recording({0: reply(task.task_id)}, received_at=float(T + 1))
        # 25s left in the window, but a 60s client budget.
        ForecastCollector(transport, timeout_seconds=60.0, clock=lambda: float(T + 5)).collect(
            task, miners(1)
        )
        assert captured["timeout"] == pytest.approx(25.0)


class TestRejection:
    def test_a_transport_error_is_reported_not_raised(self) -> None:
        task = make_task(timestamp=T)
        transport = ScriptedTransport(
            {0: reply(task.task_id)}, errors={1: "ConnectError: refused"}, received_at=float(T + 1)
        )
        result = collector(transport).collect(task, miners(2))

        assert set(result.forecasts) == {0}
        assert result.rejected[1] == "ConnectError: refused"

    def test_a_malformed_payload_is_rejected(self) -> None:
        task = make_task(timestamp=T)
        transport = ScriptedTransport(
            {0: {"task_id": task.task_id, "probability_up": 5.0, "expected_return": 0.1}},
            received_at=float(T + 1),
        )
        result = collector(transport).collect(task, miners(1))
        assert result.forecasts == {}
        assert result.rejected[0]

    def test_a_response_for_another_task_is_rejected(self) -> None:
        task = make_task(timestamp=T)
        transport = ScriptedTransport({0: reply("some-other-task")}, received_at=float(T + 1))
        result = collector(transport).collect(task, miners(1))
        assert result.forecasts == {}
        assert "answers task" in result.rejected[0]

    def test_a_missing_reply_is_rejected(self) -> None:
        task = make_task(timestamp=T)
        transport = ScriptedTransport({}, received_at=float(T + 1))
        result = collector(transport).collect(task, miners(1))
        assert result.rejected[0] == "no reply"


class TestSigning:
    def test_signs_each_request_for_its_own_receiver(self) -> None:
        task = make_task(timestamp=T)
        seen: list[dict[str, object]] = []

        def signer(*, method: str, path: str, body: bytes, receiver_ss58: str) -> dict[str, str]:
            seen.append({"method": method, "path": path, "receiver": receiver_ss58})
            return {"X-Bittensor-Hotkey": "validator", "X-Bittensor-Receiver": receiver_ss58}

        transport = ScriptedTransport(
            {0: reply(task.task_id), 1: reply(task.task_id)}, received_at=float(T + 1)
        )
        collector(transport, signer=signer).collect(task, miners(2))

        assert [entry["receiver"] for entry in seen] == ["hot0", "hot1"]
        assert {entry["path"] for entry in seen} == {FORECAST_PATH}
        assert {entry["method"] for entry in seen} == {"POST"}
        assert transport.calls[0][2]["X-Bittensor-Receiver"] == "hot0"

    def test_a_signing_failure_rejects_only_that_miner(self) -> None:
        task = make_task(timestamp=T)

        def signer(*, method: str, path: str, body: bytes, receiver_ss58: str) -> dict[str, str]:
            if receiver_ss58 == "hot0":
                raise RuntimeError("locked keyfile")
            return {}

        transport = ScriptedTransport({1: reply(task.task_id)}, received_at=float(T + 1))
        result = collector(transport, signer=signer).collect(task, miners(2))

        assert "could not sign request" in result.rejected[0]
        assert set(result.forecasts) == {1}


def test_no_miners_is_not_an_error() -> None:
    task = make_task(timestamp=T)
    result = collector(ScriptedTransport({})).collect(task, [])
    assert len(result) == 0


def test_transport_reply_ok_means_something_was_delivered() -> None:
    """``ok`` is a transport verdict, not a validity one — parsing judges the content."""
    assert not TransportReply(uid=0, received_at=0.0).ok
    assert not TransportReply(uid=0, received_at=0.0, error="boom").ok
    assert TransportReply(uid=0, received_at=0.0, payload={"a": 1}).ok
