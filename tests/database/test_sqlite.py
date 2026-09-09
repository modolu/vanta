"""Validator persistence: recording, idempotency, and restart recovery (§37, §43)."""

from __future__ import annotations

import pytest

from vanta.database.sqlite import SqliteValidatorStore
from vanta.database.store import StoredForecast
from vanta.protocol.forecast import Forecast, Resolution
from vanta.validator.scorer import ForecastScore

from ..neurons.helpers import make_task

T = 1_788_900_000


@pytest.fixture
def store() -> SqliteValidatorStore:
    with SqliteValidatorStore(":memory:") as store:
        yield store


def forecast(task_id: str, uid: int, *, probability: float = 0.6) -> Forecast:
    return Forecast(
        task_id=task_id,
        miner_uid=uid,
        probability_up=probability,
        expected_return=0.001,
        model_version="test-v1",
    )


def stored(task_id: str, uid: int, hotkey: str, **kwargs: float) -> StoredForecast:
    return StoredForecast(forecast=forecast(task_id, uid, **kwargs), hotkey=hotkey)


def score(task_id: str, uid: int) -> ForecastScore:
    return ForecastScore(
        task_id=task_id,
        miner_uid=uid,
        brier=0.2,
        probability_quality=0.8,
        return_score=0.6,
        calibration_component=0.7,
        total_score=0.72,
    )


class TestTasks:
    def test_records_and_finds_a_task(self, store: SqliteValidatorStore) -> None:
        task = make_task(timestamp=T)
        store.record_task(task)
        assert store.has_task(task.task_id)
        assert not store.has_task("nope")

    def test_recording_a_task_twice_is_idempotent(self, store: SqliteValidatorStore) -> None:
        task = make_task(timestamp=T)
        store.record_task(task)
        store.record_task(task)
        assert len(store.pending_tasks()) == 1

    def test_a_task_round_trips_exactly(self, store: SqliteValidatorStore) -> None:
        task = make_task(timestamp=T, reference_price=4512.4025)
        store.record_task(task)
        assert store.pending_tasks()[0].task == task


class TestForecasts:
    def test_forecasts_are_returned_with_their_task(self, store: SqliteValidatorStore) -> None:
        task = make_task(timestamp=T)
        store.record_task(task)
        store.record_forecasts(
            task.task_id,
            (stored(task.task_id, 0, "alice"), stored(task.task_id, 1, "bob")),
        )

        pending = store.pending_tasks()[0]
        assert {item.hotkey for item in pending.forecasts} == {"alice", "bob"}
        assert pending.forecasts[0].forecast.model_version == "test-v1"

    def test_re_recording_replaces_rather_than_duplicates(
        self, store: SqliteValidatorStore
    ) -> None:
        task = make_task(timestamp=T)
        store.record_task(task)
        store.record_forecasts(task.task_id, (stored(task.task_id, 0, "alice", probability=0.2),))
        store.record_forecasts(task.task_id, (stored(task.task_id, 0, "alice", probability=0.9),))

        forecasts = store.pending_tasks()[0].forecasts
        assert len(forecasts) == 1
        assert forecasts[0].forecast.probability_up == pytest.approx(0.9)

    def test_the_same_uid_under_two_hotkeys_is_two_rows(self, store: SqliteValidatorStore) -> None:
        """Identity is the hotkey: a recycled uid must not collide with its predecessor."""
        task = make_task(timestamp=T)
        store.record_task(task)
        store.record_forecasts(
            task.task_id,
            (stored(task.task_id, 0, "alice"), stored(task.task_id, 0, "bob")),
        )
        assert len(store.pending_tasks()[0].forecasts) == 2

    def test_optional_fields_survive_a_round_trip(self, store: SqliteValidatorStore) -> None:
        task = make_task(timestamp=T)
        store.record_task(task)
        rich = Forecast(
            task_id=task.task_id,
            miner_uid=2,
            probability_up=0.67,
            expected_return=0.0041,
            expected_volatility=0.0089,
            confidence=0.73,
            model_version="v3.1",
        )
        store.record_forecasts(task.task_id, (StoredForecast(forecast=rich, hotkey="carol"),))
        assert store.pending_tasks()[0].forecasts[0].forecast == rich

    def test_recording_no_forecasts_is_a_no_op(self, store: SqliteValidatorStore) -> None:
        task = make_task(timestamp=T)
        store.record_task(task)
        store.record_forecasts(task.task_id, ())
        assert store.pending_tasks()[0].forecasts == ()


class TestResolutionAndScores:
    def test_a_resolved_task_leaves_the_pending_set(self, store: SqliteValidatorStore) -> None:
        task = make_task(timestamp=T)
        store.record_task(task)
        store.record_resolution(Resolution.from_task(task, resolution_price=4600.0))
        assert store.pending_tasks() == ()

    def test_a_void_resolution_still_settles_the_task(self, store: SqliteValidatorStore) -> None:
        """§14: void tasks are settled and must not be retried forever."""
        task = make_task(timestamp=T, reference_price=4500.0)
        store.record_task(task)
        resolution = Resolution.from_task(task, resolution_price=4500.0)
        assert resolution.is_void
        store.record_resolution(resolution)
        assert store.pending_tasks() == ()

    def test_resolutions_are_idempotent(self, store: SqliteValidatorStore) -> None:
        task = make_task(timestamp=T)
        store.record_task(task)
        resolution = Resolution.from_task(task, resolution_price=4600.0)
        store.record_resolution(resolution)
        store.record_resolution(resolution)
        assert store.pending_tasks() == ()

    def test_scores_are_recorded_per_hotkey(self, store: SqliteValidatorStore) -> None:
        task = make_task(timestamp=T)
        store.record_task(task)
        store.record_scores(
            task.task_id, {"alice": score(task.task_id, 0), "bob": score(task.task_id, 1)}
        )
        rows = store._connection.execute(
            "SELECT hotkey, total_score FROM scores WHERE task_id = ? ORDER BY hotkey",
            (task.task_id,),
        ).fetchall()
        assert [row["hotkey"] for row in rows] == ["alice", "bob"]

    def test_recording_scores_twice_is_idempotent(self, store: SqliteValidatorStore) -> None:
        task = make_task(timestamp=T)
        store.record_task(task)
        store.record_scores(task.task_id, {"alice": score(task.task_id, 0)})
        store.record_scores(task.task_id, {"alice": score(task.task_id, 0)})
        count = store._connection.execute("SELECT COUNT(*) AS n FROM scores").fetchone()["n"]
        assert count == 1


class TestPendingSelection:
    def test_only_returns_tasks_whose_horizon_has_elapsed(
        self, store: SqliteValidatorStore
    ) -> None:
        due = make_task(timestamp=T - 1800)
        not_due = make_task(timestamp=T)
        store.record_task(due)
        store.record_task(not_due)

        pending = store.pending_tasks(resolvable_at=T)
        assert [entry.task.task_id for entry in pending] == [due.task_id]

    def test_returns_everything_unresolved_without_a_cutoff(
        self, store: SqliteValidatorStore
    ) -> None:
        store.record_task(make_task(timestamp=T - 1800))
        store.record_task(make_task(timestamp=T))
        assert len(store.pending_tasks()) == 2

    def test_is_ordered_oldest_first(self, store: SqliteValidatorStore) -> None:
        for offset in (0, -3600, -1800):
            store.record_task(make_task(timestamp=T + offset))
        timestamps = [entry.task.timestamp for entry in store.pending_tasks()]
        assert timestamps == sorted(timestamps)


class TestRestart:
    def test_in_flight_state_survives_a_restart(self, tmp_path) -> None:
        """The reason this store exists: a restart inside the horizon loses nothing."""
        path = tmp_path / "vanta.db"
        task = make_task(timestamp=T)

        with SqliteValidatorStore(path) as first:
            first.record_task(task)
            first.record_forecasts(
                task.task_id,
                (stored(task.task_id, 0, "alice"), stored(task.task_id, 1, "bob")),
            )

        with SqliteValidatorStore(path) as second:
            pending = second.pending_tasks(resolvable_at=T + 900)
            assert len(pending) == 1
            assert pending[0].task == task
            assert {item.hotkey for item in pending[0].forecasts} == {"alice", "bob"}

    def test_a_resolved_task_is_not_replayed_after_a_restart(self, tmp_path) -> None:
        path = tmp_path / "vanta.db"
        task = make_task(timestamp=T)

        with SqliteValidatorStore(path) as first:
            first.record_task(task)
            first.record_resolution(Resolution.from_task(task, resolution_price=4600.0))

        with SqliteValidatorStore(path) as second:
            assert second.pending_tasks(resolvable_at=T + 10_000) == ()

    def test_creates_the_parent_directory(self, tmp_path) -> None:
        path = tmp_path / "nested" / "deeper" / "vanta.db"
        with SqliteValidatorStore(path) as store:
            store.record_task(make_task(timestamp=T))
        assert path.exists()


class TestUrl:
    def test_builds_from_a_sqlite_url(self, tmp_path) -> None:
        with SqliteValidatorStore.from_url(f"sqlite:///{tmp_path}/vanta.db") as store:
            store.record_task(make_task(timestamp=T))
            assert len(store.pending_tasks()) == 1

    def test_rejects_a_non_sqlite_url(self) -> None:
        """A PostgreSQL URL is a configuration error, not a silent downgrade."""
        with pytest.raises(ValueError, match="no other backend is implemented"):
            SqliteValidatorStore.from_url("postgresql://localhost/vanta")
