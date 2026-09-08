from __future__ import annotations

import math

import pytest

from vanta.validation import VantaValidationError
from vanta.validator.reputation import (
    DEFAULT_EMA_ALPHA,
    NEUTRAL_CALIBRATION,
    PROBATION_FORECASTS,
    CalibrationTracker,
    MinerReputation,
)


class TestCalibrationTracker:
    def test_no_history_is_neutral_not_perfect(self) -> None:
        tracker = CalibrationTracker()
        assert tracker.sample_count == 0
        assert tracker.quality == NEUTRAL_CALIBRATION

    def test_perfectly_calibrated_miner_scores_one(self) -> None:
        # Says 70% UP a hundred times; exactly 70 go up (§18).
        tracker = CalibrationTracker()
        for index in range(100):
            tracker.record(0.70, 1.0 if index < 70 else 0.0)
        assert tracker.expected_calibration_error == pytest.approx(0.0)
        assert tracker.quality == pytest.approx(1.0)

    def test_badly_calibrated_miner_is_penalized(self) -> None:
        # Says 70% UP a hundred times; only 40 go up (§18).
        tracker = CalibrationTracker()
        for index in range(100):
            tracker.record(0.70, 1.0 if index < 40 else 0.0)
        assert tracker.expected_calibration_error == pytest.approx(0.30)
        assert tracker.quality == pytest.approx(0.70)

    def test_well_calibrated_beats_badly_calibrated(self) -> None:
        good = CalibrationTracker()
        bad = CalibrationTracker()
        for index in range(100):
            good.record(0.70, 1.0 if index < 70 else 0.0)
            bad.record(0.70, 1.0 if index < 40 else 0.0)
        assert good.quality > bad.quality

    def test_quality_stays_in_the_unit_interval_under_worst_case(self) -> None:
        tracker = CalibrationTracker()
        for _ in range(50):
            tracker.record(1.0, 0.0)
        assert tracker.quality == pytest.approx(0.0)
        assert 0.0 <= tracker.quality <= 1.0

    def test_bins_are_independent(self) -> None:
        tracker = CalibrationTracker(bins=10)
        for _ in range(10):
            tracker.record(0.05, 0.0)  # confident down, always right
        for _ in range(10):
            tracker.record(0.95, 1.0)  # confident up, always right
        assert tracker.quality == pytest.approx(1.0 - 0.05)

    def test_ordering_does_not_change_the_result(self) -> None:
        forward = CalibrationTracker()
        backward = CalibrationTracker()
        samples = [(0.7, 1.0), (0.3, 0.0), (0.9, 1.0), (0.2, 1.0)]
        for probability, outcome in samples:
            forward.record(probability, outcome)
        for probability, outcome in reversed(samples):
            backward.record(probability, outcome)
        assert forward.quality == pytest.approx(backward.quality)

    @pytest.mark.parametrize("bad", [0, -1, 1.5, True])
    def test_invalid_bin_counts_are_rejected(self, bad: object) -> None:
        with pytest.raises(VantaValidationError, match="bins"):
            CalibrationTracker(bins=bad)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [-0.1, 1.1, math.nan])
    def test_invalid_probabilities_are_rejected(self, bad: float) -> None:
        with pytest.raises(VantaValidationError):
            CalibrationTracker().record(bad, 1.0)


class TestMinerReputation:
    def test_starts_empty(self) -> None:
        reputation = MinerReputation(miner_uid=17)
        assert reputation.ema_score is None
        assert reputation.score == 0.0
        assert reputation.forecast_count == 0
        assert reputation.alpha == DEFAULT_EMA_ALPHA
        assert reputation.calibration_component == NEUTRAL_CALIBRATION

    def test_first_observation_seeds_the_ema(self) -> None:
        reputation = MinerReputation(miner_uid=1)
        reputation.record(0.80, probability_up=0.7, outcome=1.0)
        assert reputation.ema_score == pytest.approx(0.80)
        assert reputation.forecast_count == 1

    def test_follows_the_ema_recurrence(self) -> None:
        reputation = MinerReputation(miner_uid=1, alpha=0.1)
        reputation.record(0.80, probability_up=0.7, outcome=1.0)
        reputation.record(0.60, probability_up=0.7, outcome=1.0)
        # R = 0.1 * 0.60 + 0.9 * 0.80
        assert reputation.ema_score == pytest.approx(0.78)

    def test_one_lucky_forecast_does_not_dominate(self) -> None:
        # §40 test 8 / §19: sustained performance must outweigh a single spike.
        steady = MinerReputation(miner_uid=1)
        lucky = MinerReputation(miner_uid=2)
        for _ in range(50):
            steady.record(0.75, probability_up=0.7, outcome=1.0)
            lucky.record(0.30, probability_up=0.7, outcome=0.0)
        lucky.record(1.0, probability_up=0.99, outcome=1.0)
        assert steady.ema_score is not None and lucky.ema_score is not None
        assert steady.ema_score > lucky.ema_score

    def test_sustained_improvement_eventually_wins(self) -> None:
        reputation = MinerReputation(miner_uid=1)
        reputation.record(0.10, probability_up=0.5, outcome=1.0)
        for _ in range(200):
            reputation.record(0.90, probability_up=0.7, outcome=1.0)
        assert reputation.ema_score == pytest.approx(0.90, abs=1e-3)

    def test_a_single_bad_forecast_moves_reputation_by_at_most_alpha(self) -> None:
        reputation = MinerReputation(miner_uid=1, alpha=0.1)
        for _ in range(100):
            reputation.record(0.80, probability_up=0.7, outcome=1.0)
        before = reputation.score
        reputation.record(0.0, probability_up=0.99, outcome=0.0)
        assert before - reputation.score <= 0.1 * before + 1e-12

    def test_probation_uses_the_ten_forecast_threshold(self) -> None:
        reputation = MinerReputation(miner_uid=1)
        assert reputation.is_provisional
        for _ in range(PROBATION_FORECASTS - 1):
            reputation.record(0.7, probability_up=0.6, outcome=1.0)
        assert reputation.is_provisional
        reputation.record(0.7, probability_up=0.6, outcome=1.0)
        assert reputation.forecast_count == PROBATION_FORECASTS
        assert not reputation.is_provisional

    def test_calibration_accumulates_across_forecasts(self) -> None:
        reputation = MinerReputation(miner_uid=1)
        for index in range(100):
            reputation.record(0.7, probability_up=0.70, outcome=1.0 if index < 70 else 0.0)
        assert reputation.calibration.sample_count == 100
        assert reputation.calibration_component == pytest.approx(1.0)

    def test_replaying_the_same_stream_reproduces_state(self) -> None:
        stream = [(0.8, 0.7, 1.0), (0.4, 0.6, 0.0), (0.9, 0.8, 1.0)]
        first = MinerReputation(miner_uid=1)
        second = MinerReputation(miner_uid=1)
        for score, probability, outcome in stream:
            first.record(score, probability_up=probability, outcome=outcome)
            second.record(score, probability_up=probability, outcome=outcome)
        assert first.ema_score == second.ema_score
        assert first.calibration_component == second.calibration_component

    @pytest.mark.parametrize("bad", [0.0, -0.1, 1.5, math.nan])
    def test_invalid_alpha_is_rejected(self, bad: float) -> None:
        with pytest.raises(VantaValidationError, match="alpha"):
            MinerReputation(miner_uid=1, alpha=bad)

    def test_negative_uid_is_rejected(self) -> None:
        with pytest.raises(VantaValidationError, match="miner_uid"):
            MinerReputation(miner_uid=-1)

    @pytest.mark.parametrize("bad", [-0.1, 1.1, math.nan, math.inf])
    def test_out_of_range_scores_are_rejected(self, bad: float) -> None:
        with pytest.raises(VantaValidationError, match="total_score"):
            MinerReputation(miner_uid=1).record(bad, probability_up=0.5, outcome=1.0)
