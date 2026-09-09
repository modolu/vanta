"""Reputation keyed by hotkey, weights submitted by uid (§19-§21).

The trap this module exists to avoid: a uid is a recyclable slot, so reputation carried
across a deregistration would credit or punish the wrong operator.
"""

from __future__ import annotations

import pytest

from vanta.validator.reputation import PROBATION_FORECASTS
from vanta.validator.weight_adapter import MinerRegistry, WeightSubmission
from vanta.validator.weights import DEFAULT_GAMMA, compute_weights

from ..neurons.helpers import neuron


def train(registry: MinerRegistry, hotkey: str, uid: int, *, rounds: int, score: float) -> None:
    """Give a miner a reputation history at a steady score."""
    for _ in range(rounds):
        registry.record(hotkey, uid, total_score=score, probability_up=0.6, outcome=1.0)


class TestIdentity:
    def test_reputation_follows_the_hotkey_not_the_uid(self) -> None:
        registry = MinerRegistry()
        train(registry, "alice", 0, rounds=20, score=0.8)

        # Alice keeps her history when the subnet moves her to a different slot.
        moved = registry.submission([neuron(5, "alice")])
        assert moved.weights == {5: pytest.approx(1.0)}
        assert moved.hotkeys == {5: "alice"}
        assert 5 not in moved.provisional_uids

    def test_a_recycled_uid_starts_fresh(self) -> None:
        """The core correctness case: uid 0 changes hands, reputation does not follow."""
        registry = MinerRegistry()
        train(registry, "alice", 0, rounds=20, score=0.9)
        established = registry.submission([neuron(0, "alice")])
        assert established.weights[0] == pytest.approx(1.0)

        # Alice deregisters; bob is issued the same uid.
        registry.sync([neuron(0, "bob")])
        after = registry.submission([neuron(0, "bob")])

        assert after.weights == {}, "an unscored newcomer must not inherit a weight"
        assert registry.hotkeys() == frozenset()

    def test_a_newcomer_on_a_recycled_uid_is_provisional_once_scored(self) -> None:
        registry = MinerRegistry()
        train(registry, "alice", 0, rounds=20, score=0.9)
        registry.sync([neuron(0, "bob")])

        train(registry, "bob", 0, rounds=1, score=0.2)
        submission = registry.submission([neuron(0, "bob")])

        assert submission.provisional_uids == frozenset({0})
        # Bob's reputation reflects Bob's own single forecast, not Alice's 0.9 history.
        assert registry.snapshot()["bob"] == pytest.approx(0.2)

    def test_deregistered_hotkeys_are_dropped_on_sync(self) -> None:
        registry = MinerRegistry()
        train(registry, "alice", 0, rounds=5, score=0.7)
        train(registry, "bob", 1, rounds=5, score=0.7)

        departed = registry.sync([neuron(1, "bob")])

        assert departed == frozenset({"alice"})
        assert registry.hotkeys() == frozenset({"bob"})
        assert registry.tracked == 1

    def test_a_dropped_hotkey_does_not_reappear_after_re_registration(self) -> None:
        registry = MinerRegistry()
        train(registry, "alice", 0, rounds=20, score=0.9)
        registry.sync([])  # alice leaves the subnet entirely

        submission = registry.submission([neuron(3, "alice")])
        assert submission.weights == {}


class TestSubmission:
    def test_only_registered_scored_miners_are_weighted(self) -> None:
        registry = MinerRegistry()
        train(registry, "alice", 0, rounds=20, score=0.8)
        train(registry, "bob", 1, rounds=20, score=0.4)

        submission = registry.submission([neuron(0, "alice"), neuron(1, "bob"), neuron(2, "carol")])

        assert set(submission.weights) == {0, 1}, "carol was never scored, so has no weight"
        assert sum(submission.weights.values()) == pytest.approx(1.0)

    def test_defers_every_number_to_compute_weights(self) -> None:
        """The adapter selects whose score goes under which uid; §21 does the maths."""
        registry = MinerRegistry()
        train(registry, "alice", 0, rounds=20, score=0.8)
        train(registry, "bob", 1, rounds=20, score=0.4)

        submission = registry.submission([neuron(0, "alice"), neuron(1, "bob")])
        expected = compute_weights(
            {0: registry.snapshot()["alice"], 1: registry.snapshot()["bob"]},
            gamma=DEFAULT_GAMMA,
            provisional=set(),
            provisional_scale=1.0,
        )
        assert submission.weights == pytest.approx(expected)

    def test_higher_reputation_earns_more_weight(self) -> None:
        registry = MinerRegistry()
        train(registry, "good", 0, rounds=30, score=0.85)
        train(registry, "poor", 1, rounds=30, score=0.35)

        submission = registry.submission([neuron(0, "good"), neuron(1, "poor")])
        assert submission.weights[0] > submission.weights[1]

    def test_probation_window_is_reported(self) -> None:
        registry = MinerRegistry()
        train(registry, "fresh", 0, rounds=PROBATION_FORECASTS - 1, score=0.7)
        train(registry, "seasoned", 1, rounds=PROBATION_FORECASTS + 5, score=0.7)

        submission = registry.submission([neuron(0, "fresh"), neuron(1, "seasoned")])
        assert submission.provisional_uids == frozenset({0})

    def test_provisional_scale_of_one_applies_no_penalty(self) -> None:
        """§20 LOCKED: provisional_scale = 1.0 until simulation evidence justifies one."""
        registry = MinerRegistry()
        train(registry, "fresh", 0, rounds=3, score=0.7)
        train(registry, "also_fresh", 1, rounds=3, score=0.7)

        submission = registry.submission([neuron(0, "fresh"), neuron(1, "also_fresh")])
        assert submission.weights[0] == pytest.approx(submission.weights[1])

    def test_no_scored_miners_yields_an_empty_submission(self) -> None:
        registry = MinerRegistry()
        submission = registry.submission([neuron(0, "alice")])
        assert not submission
        assert submission.weights == {}

    def test_submission_is_deterministic(self) -> None:
        """§24: two identical validators must produce an identical vector."""
        first, second = MinerRegistry(), MinerRegistry()
        for registry in (first, second):
            train(registry, "alice", 0, rounds=17, score=0.81)
            train(registry, "bob", 1, rounds=17, score=0.54)

        neurons = [neuron(0, "alice"), neuron(1, "bob")]
        assert first.submission(neurons).weights == second.submission(neurons).weights


def test_weight_submission_is_falsy_when_empty() -> None:
    assert not WeightSubmission(weights={}, hotkeys={}, provisional_uids=frozenset())
    assert WeightSubmission(weights={0: 1.0}, hotkeys={0: "a"}, provisional_uids=frozenset())
