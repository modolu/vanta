"""End-to-end mechanism assertions over a replayed history (ARCHITECTURE.md §40, §41)."""

from __future__ import annotations

import math

import pytest

from tests.forecasting.helpers import candles_from
from tests.simulation.helpers import (
    INTERVAL,
    START,
    make_dataset,
    make_series,
    small_config,
    synthetic_closes,
)
from vanta.forecasting import (
    AdversarialEngine,
    MeanReversionEngine,
    MomentumEngine,
    PersistenceEngine,
    RandomEngine,
    default_engines,
)
from vanta.simulation.replay import run_simulation
from vanta.simulation.series import CandleSeries

SERIES = make_series(3000)
DATASET = make_dataset(SERIES)


# The ML engine refits two regressions from scratch on every task, costing ~340ms
# against ~0.6ms for all five other engines combined. So the suite is split: claims about
# the replay machinery and about statistical behaviour run on long, cheap, ML-free
# replays, while a short ML-inclusive replay covers the full six-engine line-up. The ML
# engine's own determinism is covered directly in tests/forecasting/test_ml.py.
CHEAP_ENGINES = [
    RandomEngine(seed=1),
    PersistenceEngine(),
    MeanReversionEngine(),
    MomentumEngine(),
    AdversarialEngine(),
]


def replay(series=SERIES, engines=None, **config_overrides):
    engines = engines if engines is not None else default_engines()
    return run_simulation(series, engines, small_config(**config_overrides), make_dataset(series))


def cheap_replay(series=SERIES, **config_overrides):
    return replay(series, engines=CHEAP_ENGINES, **config_overrides)


# All six engines, kept short because of the ML refit cost.
RESULT = replay(max_tasks=60)
# Five engines over a long history, for claims that need statistical weight.
LONG = cheap_replay(make_series(20_000), checkpoints=(10, 100, 500, 1000))


def row_for(checkpoint, name: str):
    return next(row for row in checkpoint.rows if row.name == name)


class TestReplayIntegrity:
    def test_produces_a_meaningful_number_of_valid_tasks(self) -> None:
        assert RESULT.valid_tasks == 60
        assert LONG.valid_tasks > 1000

    def test_is_deterministic(self) -> None:
        first = cheap_replay(make_series(6000))
        second = cheap_replay(make_series(6000))
        assert first.final == second.final
        assert first.valid_tasks == second.valid_tasks
        assert first.consensus.hits == second.consensus.hits

    def test_is_deterministic_with_every_engine_including_ml(self) -> None:
        assert replay(max_tasks=15).final == replay(max_tasks=15).final

    def test_all_miners_share_one_task_universe(self) -> None:
        counts = {row.name: row.forecast_count for row in RESULT.final.rows}
        assert len(set(counts.values())) == 1
        assert next(iter(counts.values())) == RESULT.valid_tasks

    def test_task_accounting_adds_up(self) -> None:
        accounted = (
            RESULT.valid_tasks
            + RESULT.void_tasks
            + RESULT.unresolvable_tasks
            + RESULT.incomplete_tasks
        )
        assert accounted == RESULT.attempted_tasks

    def test_every_engine_appears_exactly_once(self) -> None:
        names = [row.name for row in RESULT.final.rows]
        assert sorted(names) == sorted(RESULT.engine_names)

    def test_checkpoints_are_ordered_and_cumulative(self) -> None:
        counts = [checkpoint.valid_tasks for checkpoint in RESULT.checkpoints]
        assert counts == sorted(counts)
        assert all(count <= RESULT.final.valid_tasks for count in counts)


class TestNoLeakage:
    def test_appending_future_candles_does_not_change_history(self) -> None:
        # A replay truncated at N tasks must be unaffected by candles that arrive later.
        base = cheap_replay(make_series(2000), max_tasks=80)

        closes = synthetic_closes(2000)
        extended = CandleSeries(
            candles_from([*closes, *[closes[-1] * 4.0] * 500], start=START),
            interval_seconds=INTERVAL,
        )
        with_future = cheap_replay(extended, max_tasks=80)

        assert base.final.rows == with_future.final.rows

    def test_mutating_only_the_tail_does_not_change_history(self) -> None:
        closes = synthetic_closes(2000)
        crash = CandleSeries(
            candles_from([*closes, *[1.0] * 200], start=START), interval_seconds=INTERVAL
        )
        moon = CandleSeries(
            candles_from([*closes, *[999_999.0] * 200], start=START), interval_seconds=INTERVAL
        )
        assert (
            cheap_replay(crash, max_tasks=80).final.rows
            == cheap_replay(moon, max_tasks=80).final.rows
        )

    def test_the_ml_engine_also_ignores_future_candles_in_replay(self) -> None:
        closes = synthetic_closes(2000)
        base = replay(make_series(2000), max_tasks=12)
        extended = CandleSeries(
            candles_from([*closes, *[closes[-1] * 4.0] * 300], start=START),
            interval_seconds=INTERVAL,
        )
        assert base.final.rows == replay(extended, max_tasks=12).final.rows


class TestWeightsAndConsensus:
    def test_weights_are_normalized_at_every_checkpoint(self) -> None:
        for checkpoint in (*RESULT.checkpoints, RESULT.final):
            total = sum(row.weight for row in checkpoint.rows)
            assert total == pytest.approx(1.0)

    def test_weights_follow_reputation_order(self) -> None:
        rows = RESULT.final.rows
        assert [row.weight for row in rows] == sorted((row.weight for row in rows), reverse=True)

    def test_no_miner_takes_everything(self) -> None:
        # §22: winner-take-all is explicitly rejected.
        assert max(row.weight for row in RESULT.final.rows) < 1.0
        assert all(row.weight >= 0.0 for row in RESULT.final.rows)

    def test_consensus_stays_bounded_and_finite(self) -> None:
        consensus = RESULT.consensus
        assert consensus.count == RESULT.valid_tasks
        assert 0.0 <= consensus.mean_probability <= 1.0
        assert math.isfinite(consensus.mean_dispersion)
        assert 0.0 <= consensus.mean_brier <= 1.0

    def test_every_reported_number_is_finite(self) -> None:
        for row in RESULT.final.rows:
            for value in (
                row.mean_score,
                row.ema_reputation,
                row.probability_quality,
                row.brier,
                row.return_score,
                row.calibration,
                row.weight,
                row.directional_accuracy,
                row.mean_absolute_return_error,
            ):
                assert math.isfinite(value)
            assert 0.0 <= row.ema_reputation <= 1.0
            assert 0.0 <= row.probability_quality <= 1.0


class TestMechanismBehaviour:
    def test_unjustified_certainty_costs_more_than_hedging(self) -> None:
        """§25 attack 3 / §40 test 3, isolated from directional skill.

        The random and adversarial engines are both directionally worthless — each lands
        near 50%. They differ only in confidence: random states a uniform probability,
        adversarial states 0.99 every time. If Brier scoring punishes unjustified
        certainty, the two must separate sharply despite equal accuracy.
        """
        random_row = row_for(LONG.final, "random")
        adversarial = row_for(LONG.final, "adversarial")

        assert abs(random_row.directional_accuracy - adversarial.directional_accuracy) < 0.10
        assert adversarial.brier > random_row.brier
        assert adversarial.ema_reputation < random_row.ema_reputation
        # Worse than simply saying 0.5 every time, which would score a flat 0.25.
        assert adversarial.brier > 0.25

    def test_being_confidently_wrong_is_punished_hardest_of_all(self) -> None:
        # The worst Brier belongs to whichever engine is most often confidently wrong —
        # not automatically the adversarial one. On a persistent market that is the
        # mean-reversion engine, which is both confident and on the wrong side.
        worst = max(LONG.final.rows, key=lambda row: row.brier)
        best = min(LONG.final.rows, key=lambda row: row.brier)
        assert worst.directional_accuracy < best.directional_accuracy
        assert worst.rank > best.rank

    def test_the_adversarial_miner_never_leads(self) -> None:
        assert row_for(LONG.final, "adversarial").rank > 1
        assert row_for(RESULT.final, "adversarial").rank > 1

    def test_the_random_miner_does_not_systematically_dominate(self) -> None:
        # §40 test 1: noise may get lucky briefly, but must not lead a long replay.
        # Asserted over 1000+ tasks, where luck has had time to wash out.
        assert row_for(LONG.final, "random").rank > 1

    def test_the_random_miner_decays_as_the_sample_grows(self) -> None:
        # §41's headline claim: the control drifts down the board with sample size.
        early = row_for(LONG.checkpoints[0], "random").rank
        late = row_for(LONG.final, "random").rank
        assert late >= early

    def test_a_lone_perfect_forecast_cannot_overtake_sustained_performance(self) -> None:
        # §40 test 8, at the reputation level the replay actually drives.
        from vanta.validator.reputation import MinerReputation

        steady = MinerReputation(miner_uid=0)
        spiker = MinerReputation(miner_uid=1)
        for _ in range(LONG.valid_tasks):
            steady.record(0.7, probability_up=0.6, outcome=1.0)
            spiker.record(0.2, probability_up=0.6, outcome=1.0)
        spiker.record(1.0, probability_up=0.99, outcome=1.0)
        assert steady.score > spiker.score

    def test_calibration_is_measured_over_history_not_one_forecast(self) -> None:
        for row in RESULT.final.rows:
            assert 0.0 <= row.calibration <= 1.0
        # The adversarial miner states 0.99 constantly, so its stated probability cannot
        # match realized frequency unless the market always rises.
        assert row_for(RESULT.final, "adversarial").calibration < 1.0

    def test_probation_clears_once_the_threshold_is_passed(self) -> None:
        assert all(not row.provisional for row in RESULT.final.rows)
        assert RESULT.checkpoints[0].valid_tasks >= 10
        assert all(row.provisional for row in _at_ten().rows)


def _at_ten():
    return cheap_replay(make_series(2000), max_tasks=9).final


class TestDegenerateInput:
    def test_a_flat_market_voids_every_task_without_corrupting_state(self) -> None:
        flat = CandleSeries(candles_from([4000.0] * 2000, start=START), interval_seconds=INTERVAL)
        # A perfectly flat market has zero volatility, so no return scale exists and no
        # task can be scored. Nothing should blow up, and no miner should gain reputation.
        result = cheap_replay(flat)
        assert result.valid_tasks == 0
        assert all(row.ema_reputation == 0.0 for row in result.final.rows)
        assert all(row.forecast_count == 0 for row in result.final.rows)
        assert sum(row.weight for row in result.final.rows) == pytest.approx(1.0)

    def test_void_tasks_never_reach_reputation(self) -> None:
        result = cheap_replay(make_series(2000))
        total = result.valid_tasks
        assert all(row.forecast_count == total for row in result.final.rows)

    def test_a_series_too_short_to_warm_up_yields_no_tasks(self) -> None:
        short = CandleSeries(
            candles_from(synthetic_closes(120), start=START), interval_seconds=INTERVAL
        )
        result = cheap_replay(short)
        assert result.valid_tasks == 0

    def test_an_empty_engine_list_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one engine"):
            replay(engines=[], max_tasks=1)


class TestEngineIsolation:
    def test_one_engine_replay_still_produces_normalized_weights(self) -> None:
        result = replay(engines=[MomentumEngine()])
        assert sum(row.weight for row in result.final.rows) == pytest.approx(1.0)

    def test_reordering_engines_does_not_change_their_scores(self) -> None:
        forward = replay(engines=[PersistenceEngine(), MeanReversionEngine(), AdversarialEngine()])
        backward = replay(engines=[AdversarialEngine(), MeanReversionEngine(), PersistenceEngine()])
        forward_scores = {row.name: row.mean_score for row in forward.final.rows}
        backward_scores = {row.name: row.mean_score for row in backward.final.rows}
        assert forward_scores == pytest.approx(backward_scores)

    def test_the_random_engine_is_reproducible_across_replays(self) -> None:
        first = replay(engines=[RandomEngine(seed=5)])
        second = replay(engines=[RandomEngine(seed=5)])
        assert first.final.rows == second.final.rows
