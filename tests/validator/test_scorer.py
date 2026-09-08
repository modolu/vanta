from __future__ import annotations

import math

import pytest

from vanta.protocol.forecast import Forecast, ForecastTask, Resolution
from vanta.validation import VantaValidationError
from vanta.validator.scorer import (
    CALIBRATION_WEIGHT,
    PROBABILITY_WEIGHT,
    RETURN_WEIGHT,
    brier_score,
    probability_quality,
    return_score,
    score_forecast,
    vanta_score,
)

T = 1_789_905_600
SCALE = 0.005  # representative 15m ETH move, supplied explicitly by the caller


def make_task() -> ForecastTask:
    return ForecastTask(
        task_id="eth-15m-1",
        asset="ETH-USD",
        reference_price=4500.0,
        timestamp=T,
        horizon_seconds=900,
        deadline=T + 30,
    )


def test_component_weights_sum_to_one() -> None:
    assert pytest.approx(1.0) == PROBABILITY_WEIGHT + RETURN_WEIGHT + CALIBRATION_WEIGHT


class TestProbabilityQuality:
    def test_matches_the_worked_examples(self) -> None:
        # §16: 70% up, market rises -> Brier 0.09, quality 0.91.
        assert brier_score(0.70, 1.0) == pytest.approx(0.09)
        assert probability_quality(0.70, 1.0) == pytest.approx(0.91)
        # §16: 99% up, market falls -> Brier 0.9801, quality 0.0199.
        assert brier_score(0.99, 0.0) == pytest.approx(0.9801)
        assert probability_quality(0.99, 0.0) == pytest.approx(0.0199)

    def test_perfect_prediction_scores_one(self) -> None:
        assert probability_quality(1.0, 1.0) == pytest.approx(1.0)
        assert probability_quality(0.0, 0.0) == pytest.approx(1.0)

    def test_maximally_wrong_prediction_scores_zero(self) -> None:
        assert probability_quality(1.0, 0.0) == pytest.approx(0.0)

    def test_extreme_wrong_confidence_is_punished_far_harder_than_hedging(self) -> None:
        # §25 attack 3: unjustified certainty must cost more than an even-odds guess.
        overconfident = probability_quality(0.999, 0.0)
        hedged = probability_quality(0.5, 0.0)
        assert overconfident < hedged
        assert hedged - overconfident > 0.24

    def test_being_wrong_at_high_confidence_beats_nothing(self) -> None:
        assert probability_quality(0.9, 0.0) < probability_quality(0.6, 0.0)


class TestReturnScore:
    def test_exact_prediction_scores_one(self) -> None:
        assert return_score(0.01, 0.01, SCALE) == pytest.approx(1.0)

    def test_better_return_prediction_scores_higher(self) -> None:
        actual = 0.010
        close = return_score(0.009, actual, SCALE)
        far = return_score(0.030, actual, SCALE)
        assert close > far

    def test_follows_the_exponential_formula(self) -> None:
        expected = math.exp(-abs(0.007 - 0.010) / SCALE)
        assert return_score(0.007, 0.010, SCALE) == pytest.approx(expected)

    def test_is_symmetric_in_the_direction_of_error(self) -> None:
        assert return_score(0.012, 0.010, SCALE) == pytest.approx(return_score(0.008, 0.010, SCALE))

    def test_stays_within_the_unit_interval(self) -> None:
        assert 0.0 <= return_score(5.0, -5.0, SCALE) <= 1.0

    def test_absurd_error_floors_at_zero_rather_than_overflowing(self) -> None:
        # exp() underflows for errors many multiples of scale; 0.0 is the correct floor
        # and must not raise or go negative.
        assert return_score(5.0, -5.0, SCALE) == 0.0

    def test_larger_scale_is_more_forgiving(self) -> None:
        assert return_score(0.02, 0.01, 0.02) > return_score(0.02, 0.01, 0.002)

    @pytest.mark.parametrize("bad", [0.0, -0.01, math.nan, math.inf])
    def test_invalid_scale_is_rejected(self, bad: float) -> None:
        with pytest.raises(VantaValidationError, match="scale"):
            return_score(0.01, 0.01, bad)


class TestVantaScore:
    def test_applies_the_sixty_thirty_ten_split(self) -> None:
        assert vanta_score(1.0, 0.0, 0.0) == pytest.approx(0.60)
        assert vanta_score(0.0, 1.0, 0.0) == pytest.approx(0.30)
        assert vanta_score(0.0, 0.0, 1.0) == pytest.approx(0.10)
        assert vanta_score(1.0, 1.0, 1.0) == pytest.approx(1.0)

    def test_is_bounded_to_the_unit_interval(self) -> None:
        assert vanta_score(0.0, 0.0, 0.0) == pytest.approx(0.0)

    @pytest.mark.parametrize("bad", [-0.1, 1.1, math.nan])
    def test_invalid_components_are_rejected(self, bad: float) -> None:
        with pytest.raises(VantaValidationError):
            vanta_score(bad, 0.5, 0.5)


class TestScoreForecast:
    def test_perfect_forecast_scores_near_the_maximum(self) -> None:
        task = make_task()
        resolution = Resolution.from_task(task, resolution_price=4545.0)
        forecast = Forecast(
            task_id=task.task_id,
            miner_uid=1,
            probability_up=1.0,
            expected_return=resolution.realized_return,
        )
        score = score_forecast(forecast, resolution, return_scale=SCALE, calibration_component=1.0)
        assert score.probability_quality == pytest.approx(1.0)
        assert score.return_score == pytest.approx(1.0)
        assert score.total_score == pytest.approx(1.0)

    def test_confidently_wrong_forecast_scores_near_zero(self) -> None:
        task = make_task()
        resolution = Resolution.from_task(task, resolution_price=4455.0)  # market fell
        forecast = Forecast(
            task_id=task.task_id, miner_uid=2, probability_up=0.99, expected_return=0.02
        )
        score = score_forecast(forecast, resolution, return_scale=SCALE, calibration_component=0.0)
        assert score.probability_quality < 0.03
        assert score.return_score < 0.01
        assert score.total_score < 0.02

    def test_perfect_forecast_beats_a_confidently_wrong_one(self) -> None:
        task = make_task()
        resolution = Resolution.from_task(task, resolution_price=4545.0)
        good = score_forecast(
            Forecast(
                task_id=task.task_id,
                miner_uid=1,
                probability_up=0.95,
                expected_return=0.010,
            ),
            resolution,
            return_scale=SCALE,
            calibration_component=0.5,
        )
        bad = score_forecast(
            Forecast(
                task_id=task.task_id,
                miner_uid=2,
                probability_up=0.02,
                expected_return=-0.020,
            ),
            resolution,
            return_scale=SCALE,
            calibration_component=0.5,
        )
        assert good.total_score > bad.total_score

    def test_well_calibrated_miner_beats_an_equally_accurate_uncalibrated_one(self) -> None:
        # §40 test 4, at the point where calibration enters the score.
        task = make_task()
        resolution = Resolution.from_task(task, resolution_price=4545.0)
        forecast = Forecast(
            task_id=task.task_id, miner_uid=3, probability_up=0.7, expected_return=0.009
        )
        calibrated = score_forecast(
            forecast, resolution, return_scale=SCALE, calibration_component=0.95
        )
        uncalibrated = score_forecast(
            forecast, resolution, return_scale=SCALE, calibration_component=0.40
        )
        assert calibrated.total_score > uncalibrated.total_score
        assert calibrated.probability_quality == uncalibrated.probability_quality

    def test_brier_and_quality_are_complementary(self) -> None:
        task = make_task()
        resolution = Resolution.from_task(task, resolution_price=4545.0)
        score = score_forecast(
            Forecast(task_id=task.task_id, miner_uid=4, probability_up=0.7, expected_return=0.01),
            resolution,
            return_scale=SCALE,
            calibration_component=0.5,
        )
        assert score.brier + score.probability_quality == pytest.approx(1.0)

    def test_is_deterministic(self) -> None:
        task = make_task()
        resolution = Resolution.from_task(task, resolution_price=4520.0)
        forecast = Forecast(
            task_id=task.task_id, miner_uid=5, probability_up=0.61, expected_return=0.003
        )
        first = score_forecast(forecast, resolution, return_scale=SCALE, calibration_component=0.77)
        second = score_forecast(
            forecast, resolution, return_scale=SCALE, calibration_component=0.77
        )
        assert first == second

    def test_mismatched_task_ids_are_rejected(self) -> None:
        task = make_task()
        resolution = Resolution.from_task(task, resolution_price=4545.0)
        forecast = Forecast(
            task_id="some-other-task", miner_uid=6, probability_up=0.5, expected_return=0.0
        )
        with pytest.raises(VantaValidationError, match="does not match"):
            score_forecast(forecast, resolution, return_scale=SCALE, calibration_component=0.5)

    def test_carries_identity_through_to_the_score_record(self) -> None:
        task = make_task()
        resolution = Resolution.from_task(task, resolution_price=4545.0)
        forecast = Forecast(
            task_id=task.task_id, miner_uid=17, probability_up=0.5, expected_return=0.0
        )
        score = score_forecast(forecast, resolution, return_scale=SCALE, calibration_component=0.5)
        assert score.task_id == task.task_id
        assert score.miner_uid == 17
