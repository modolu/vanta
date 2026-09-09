"""The validator neuron: one full lifecycle against fakes, with no chain and no network."""

from __future__ import annotations

import pytest

from vanta.database.sqlite import SqliteValidatorStore
from vanta.market.resolution import ResolutionEngine
from vanta.neurons.validator import Validator, ValidatorConfig
from vanta.validator.collector import ForecastCollector
from vanta.validator.reputation import PROBATION_FORECASTS
from vanta.validator.task_generator import TaskGenerator
from vanta.validator.weight_adapter import MinerRegistry

from .helpers import (
    INTERVAL,
    FakeSubnetView,
    FakeWeightSubmitter,
    ScriptedTransport,
    SeriesProvider,
    candles_from,
    drifting_closes,
    neuron,
)

T = 1_788_900_000
HORIZON = 900


class Harness:
    """A validator wired entirely to in-memory doubles."""

    def __init__(
        self,
        *,
        neurons=None,
        replies=None,
        late=(),
        errors=None,
        now: float = float(T),
        weight_interval: int = 1,
        submitter: FakeWeightSubmitter | None = None,
        store: SqliteValidatorStore | None = None,
        registry: MinerRegistry | None = None,
    ) -> None:
        self.now = now
        # Enough history on both sides of T to price a task and resolve it later.
        closes = drifting_closes(1200)
        self.provider = SeriesProvider(candles_from(closes, start=T - 900 * INTERVAL))
        self.resolution = ResolutionEngine(self.provider, candle_interval_seconds=INTERVAL)
        self.view = FakeSubnetView(
            neurons if neurons is not None else [neuron(0, "alice"), neuron(1, "bob")]
        )
        self.transport = ScriptedTransport(
            replies if replies is not None else {}, errors=errors, late=late, received_at=now
        )
        self.submitter = submitter or FakeWeightSubmitter()
        self.store = store or SqliteValidatorStore(":memory:")
        self.registry = registry or MinerRegistry()

        self.validator = Validator(
            config=ValidatorConfig(
                netuid=1,
                asset="ETH-USD",
                horizon_seconds=HORIZON,
                task_interval_seconds=HORIZON,
                weight_interval_seconds=weight_interval,
                self_hotkey="validator-hot",
            ),
            generator=TaskGenerator(
                resolution=self.resolution,
                asset="ETH-USD",
                horizon_seconds=HORIZON,
                submission_window_seconds=30,
                clock=lambda: self.now,
            ),
            collector=ForecastCollector(self.transport, clock=lambda: self.now),
            resolution=self.resolution,
            registry=self.registry,
            store=self.store,
            view=self.view,
            submitter=self.submitter,
            clock=lambda: self.now,
        )

    def advance(self, seconds: float) -> None:
        self.now += seconds
        self.transport._received_at = self.now  # type: ignore[attr-defined]


def reply(task_id: str, probability: float = 0.6, expected_return: float = 0.0015) -> dict:
    return {
        "task_id": task_id,
        "probability_up": probability,
        "expected_return": expected_return,
    }


def replies_for(harness: Harness, uids=(0, 1), **kwargs) -> dict[int, dict]:
    """Pre-compute the task id the generator will produce, so miners can answer it."""
    task_id = f"ETH-USD-{HORIZON}s-{int(harness.now)}"
    return {uid: reply(task_id, **kwargs) for uid in uids}


class TestMinerSelection:
    def test_only_servable_miners_are_queried(self) -> None:
        harness = Harness(
            neurons=[neuron(0, "alice"), neuron(1, "bob", axon=""), neuron(2, "carol")]
        )
        miners = harness.validator.miners(harness.validator.sync())
        assert [miner.uid for miner in miners] == [0, 2]

    def test_the_validator_never_queries_itself(self) -> None:
        harness = Harness(neurons=[neuron(0, "alice"), neuron(1, "validator-hot")])
        miners = harness.validator.miners(harness.validator.sync())
        assert [miner.hotkey for miner in miners] == ["alice"]

    def test_the_endpoint_url_comes_from_the_metagraph(self) -> None:
        harness = Harness(neurons=[neuron(0, "alice", axon="10.0.0.5:9101")])
        miners = harness.validator.miners(harness.validator.sync())
        assert miners[0].url == "http://10.0.0.5:9101"


class TestIssuing:
    def test_issues_a_task_and_persists_the_forecasts(self) -> None:
        harness = Harness()
        harness.transport._replies = replies_for(harness)  # type: ignore[attr-defined]
        neurons = harness.validator.sync()
        task, rejected = harness.validator.issue_task(harness.validator.miners(neurons))

        assert task is not None
        assert rejected == {}
        pending = harness.store.pending_tasks()
        assert len(pending) == 1
        assert {item.hotkey for item in pending[0].forecasts} == {"alice", "bob"}

    def test_the_task_is_persisted_even_if_no_miner_answers(self) -> None:
        harness = Harness(replies={})
        neurons = harness.validator.sync()
        task, _ = harness.validator.issue_task(harness.validator.miners(neurons))
        assert task is not None
        assert harness.store.has_task(task.task_id)

    def test_a_late_response_is_not_persisted(self) -> None:
        """§27 end to end: the late miner's forecast never reaches storage."""
        harness = Harness(late=[1])
        harness.transport._replies = replies_for(harness)  # type: ignore[attr-defined]
        neurons = harness.validator.sync()
        harness.validator.issue_task(harness.validator.miners(neurons))

        stored = harness.store.pending_tasks()[0].forecasts
        assert {item.hotkey for item in stored} == {"alice"}

    def test_no_miners_means_no_task(self) -> None:
        harness = Harness(neurons=[])
        task, rejected = harness.validator.issue_task([])
        assert task is None
        assert rejected == {}


class TestResolving:
    def test_resolves_scores_and_updates_reputation(self) -> None:
        harness = Harness()
        harness.transport._replies = replies_for(harness)  # type: ignore[attr-defined]
        neurons = harness.validator.sync()
        harness.validator.issue_task(harness.validator.miners(neurons))

        harness.advance(HORIZON + 1)
        outcomes = harness.validator.resolve_due()

        assert len(outcomes) == 1
        assert outcomes[0].resolved
        assert outcomes[0].scored == 2
        assert set(harness.registry.hotkeys()) == {"alice", "bob"}
        assert harness.store.pending_tasks() == ()

    def test_a_task_is_not_resolved_before_its_horizon(self) -> None:
        harness = Harness()
        harness.transport._replies = replies_for(harness)  # type: ignore[attr-defined]
        neurons = harness.validator.sync()
        harness.validator.issue_task(harness.validator.miners(neurons))

        harness.advance(60)
        assert harness.validator.resolve_due() == ()
        assert len(harness.store.pending_tasks()) == 1

    def test_reputation_is_keyed_by_hotkey(self) -> None:
        harness = Harness()
        harness.transport._replies = replies_for(harness)  # type: ignore[attr-defined]
        neurons = harness.validator.sync()
        harness.validator.issue_task(harness.validator.miners(neurons))
        harness.advance(HORIZON + 1)
        harness.validator.resolve_due()

        snapshot = harness.registry.snapshot()
        assert set(snapshot) == {"alice", "bob"}

    def test_a_void_task_touches_no_miner_state(self) -> None:
        """§14 LOCKED: an exactly flat market voids the outcome entirely."""
        harness = Harness()
        harness.transport._replies = replies_for(harness)  # type: ignore[attr-defined]
        neurons = harness.validator.sync()
        task, _ = harness.validator.issue_task(harness.validator.miners(neurons))
        assert task is not None

        # Force resolution at exactly the reference price.
        harness.validator._resolution = _FlatResolution(  # type: ignore[attr-defined]
            harness.resolution, task.reference_price
        )
        harness.advance(HORIZON + 1)
        outcomes = harness.validator.resolve_due()

        assert outcomes[0].void
        assert outcomes[0].scored == 0
        assert harness.registry.tracked == 0, "a void task must not create reputation"
        assert harness.store.pending_tasks() == ()

    def test_a_better_forecast_earns_more_weight(self) -> None:
        """The mechanism still discriminates once it runs through the neuron."""
        harness = Harness(weight_interval=1)
        neurons = harness.validator.sync()

        for _ in range(PROBATION_FORECASTS + 2):
            task_id = f"ETH-USD-{HORIZON}s-{int(harness.now)}"
            resolution_price = harness.resolution.price_at("ETH-USD", int(harness.now) + HORIZON)
            reference = harness.resolution.price_at("ETH-USD", int(harness.now))
            went_up = resolution_price > reference
            confident = 0.95 if went_up else 0.05
            harness.transport._replies = {  # type: ignore[attr-defined]
                0: reply(task_id, probability=confident),
                1: reply(task_id, probability=1.0 - confident),
            }
            harness.validator.issue_task(harness.validator.miners(neurons))
            harness.advance(HORIZON + 1)
            harness.validator.resolve_due()

        snapshot = harness.registry.snapshot()
        assert snapshot["alice"] > snapshot["bob"]
        submission = harness.registry.submission(neurons)
        assert submission.weights[0] > submission.weights[1]


class _FlatResolution:
    """Wraps the real engine but prices resolution exactly at the reference."""

    def __init__(self, inner: ResolutionEngine, price: float) -> None:
        self._inner = inner
        self._price = price

    def resolve(self, task):  # type: ignore[no-untyped-def]
        from vanta.protocol.forecast import Resolution

        return Resolution.from_task(task, resolution_price=self._price)

    def return_scale(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self._inner.return_scale(*args, **kwargs)


class TestWeights:
    def test_submits_a_normalized_vector_by_current_uid(self) -> None:
        harness = Harness()
        harness.transport._replies = replies_for(harness)  # type: ignore[attr-defined]
        neurons = harness.validator.sync()
        harness.validator.issue_task(harness.validator.miners(neurons))
        harness.advance(HORIZON + 1)
        harness.validator.resolve_due()

        weights, result = harness.validator.submit_weights(neurons, force=True)
        assert weights is not None
        assert set(weights) == {0, 1}
        assert sum(weights.values()) == pytest.approx(1.0)
        assert result is not None
        assert harness.submitter.last == weights

    def test_nothing_is_submitted_before_any_miner_is_scored(self) -> None:
        harness = Harness()
        neurons = harness.validator.sync()
        weights, reason = harness.validator.submit_weights(neurons, force=True)
        assert weights is None
        assert reason == "no scored miners to weight yet"

    def test_respects_the_submission_interval(self) -> None:
        harness = Harness(weight_interval=3600)
        harness.transport._replies = replies_for(harness)  # type: ignore[attr-defined]
        neurons = harness.validator.sync()
        harness.validator.issue_task(harness.validator.miners(neurons))
        harness.advance(HORIZON + 1)
        harness.validator.resolve_due()

        first, _ = harness.validator.submit_weights(neurons)
        assert first is not None
        second, reason = harness.validator.submit_weights(neurons)
        assert second is None
        assert reason == "inside the weight submission interval"

    def test_a_submission_failure_does_not_raise_or_corrupt_state(self) -> None:
        harness = Harness(submitter=FakeWeightSubmitter(fail_with="rate limit: wait 100 blocks"))
        harness.transport._replies = replies_for(harness)  # type: ignore[attr-defined]
        neurons = harness.validator.sync()
        harness.validator.issue_task(harness.validator.miners(neurons))
        harness.advance(HORIZON + 1)
        harness.validator.resolve_due()
        before = dict(harness.registry.snapshot())

        weights, reason = harness.validator.submit_weights(neurons, force=True)

        assert weights is None
        assert reason is not None
        assert "rate limit" in reason
        assert harness.registry.snapshot() == before

    def test_a_recycled_uid_does_not_inherit_weight(self) -> None:
        """The chain-layer version of the uid-recycling trap."""
        harness = Harness()
        harness.transport._replies = replies_for(harness)  # type: ignore[attr-defined]
        neurons = harness.validator.sync()
        harness.validator.issue_task(harness.validator.miners(neurons))
        harness.advance(HORIZON + 1)
        harness.validator.resolve_due()
        assert harness.validator.submit_weights(neurons, force=True)[0] is not None

        # Alice deregisters; mallory takes uid 0.
        harness.view.set([neuron(0, "mallory"), neuron(1, "bob")])
        refreshed = harness.validator.sync()
        weights, _ = harness.validator.submit_weights(refreshed, force=True)

        assert weights is not None
        assert 0 not in weights, "the newcomer on uid 0 must start with no weight"
        assert set(weights) == {1}


class TestRoundLoop:
    def test_a_full_round_reports_what_it_did(self) -> None:
        harness = Harness()
        harness.transport._replies = replies_for(harness)  # type: ignore[attr-defined]
        report = harness.validator.run_once()

        assert report.task_id is not None
        assert report.queried == 2
        assert report.errors == ()

    def test_a_metagraph_failure_aborts_the_round_cleanly(self) -> None:
        harness = Harness()
        harness.view.fail_with = "connection refused"
        report = harness.validator.run_once()

        assert report.errors
        assert "sync failed" in report.errors[0]
        assert report.task_id is None

    def test_the_loop_runs_a_bounded_number_of_rounds(self) -> None:
        harness = Harness()
        harness.transport._replies = replies_for(harness)  # type: ignore[attr-defined]
        assert harness.validator.run(max_rounds=2, sleep=lambda _: None) == 2

    def test_resolution_survives_a_restart(self) -> None:
        """Tasks issued before a restart are reloaded and settled afterwards."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vanta.db"

            first = Harness(store=SqliteValidatorStore(path))
            first.transport._replies = replies_for(first)  # type: ignore[attr-defined]
            neurons = first.validator.sync()
            task, _ = first.validator.issue_task(first.validator.miners(neurons))
            assert task is not None
            first.store.close()

            # A brand new process: fresh registry, fresh store handle, same database.
            second = Harness(store=SqliteValidatorStore(path), now=float(T + HORIZON + 1))
            outcomes = second.validator.resolve_due()

            assert [outcome.task_id for outcome in outcomes] == [task.task_id]
            assert outcomes[0].scored == 2
            assert set(second.registry.hotkeys()) == {"alice", "bob"}
            second.store.close()
