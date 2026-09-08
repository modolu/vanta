from __future__ import annotations

import math

import pytest

from vanta.forecasting.features import (
    FEATURE_NAMES,
    FEATURE_WARMUP,
    ema,
    feature_row,
    logistic,
    period_return,
    roc,
    rsi,
    simple_returns,
    volatility_of,
)
from vanta.market.errors import InsufficientMarketDataError


class TestLogistic:
    def test_zero_maps_to_a_coin_flip(self) -> None:
        assert logistic(0.0) == pytest.approx(0.5)

    def test_is_monotonic_and_bounded(self) -> None:
        values = [logistic(x) for x in (-5.0, -1.0, 0.0, 1.0, 5.0)]
        assert values == sorted(values)
        assert all(0.0 < v < 1.0 for v in values)

    @pytest.mark.parametrize("extreme", [1e6, -1e6, 1e300, -1e300])
    def test_does_not_overflow_at_extremes(self, extreme: float) -> None:
        result = logistic(extreme)
        assert 0.0 <= result <= 1.0
        assert math.isfinite(result)

    def test_steepness_sharpens_the_response(self) -> None:
        assert logistic(1.0, 5.0) > logistic(1.0, 1.0)


class TestIndicators:
    def test_simple_returns(self) -> None:
        assert simple_returns([100.0, 110.0, 99.0]) == pytest.approx([0.1, -0.1])

    def test_period_return_spans_the_requested_window(self) -> None:
        assert period_return([100.0, 200.0, 300.0], 2) == pytest.approx(2.0)

    def test_ema_of_a_flat_series_is_that_value(self) -> None:
        assert ema([100.0] * 30, 10) == pytest.approx(100.0)

    def test_ema_lags_a_rising_series(self) -> None:
        prices = [float(i) for i in range(1, 41)]
        assert ema(prices, 10) < prices[-1]

    def test_roc_matches_period_return(self) -> None:
        prices = [100.0, 105.0, 110.0]
        assert roc(prices, 2) == period_return(prices, 2)

    def test_rsi_is_one_hundred_when_every_change_is_a_gain(self) -> None:
        assert rsi([float(i) for i in range(1, 20)], 14) == pytest.approx(100.0)

    def test_rsi_is_zero_when_every_change_is_a_loss(self) -> None:
        assert rsi([float(i) for i in range(20, 1, -1)], 14) == pytest.approx(0.0)

    def test_rsi_of_a_flat_series_is_neutral(self) -> None:
        assert rsi([100.0] * 20, 14) == pytest.approx(50.0)

    def test_volatility_of_a_flat_series_is_zero(self) -> None:
        assert volatility_of([100.0] * 30, 20) == pytest.approx(0.0)


class TestFeatureRow:
    def test_has_the_documented_layout(self) -> None:
        prices = [100.0 * (1.001**i) for i in range(60)]
        row = feature_row(prices)
        assert len(row) == len(FEATURE_NAMES)
        assert all(math.isfinite(value) for value in row)

    def test_a_rising_series_produces_positive_momentum_features(self) -> None:
        prices = [100.0 * (1.001**i) for i in range(60)]
        row = feature_row(prices)
        assert row[0] > 0  # return_1
        assert row[1] > 0  # return_5
        assert row[3] > 0  # rsi centred above neutral

    def test_a_falling_series_produces_negative_momentum_features(self) -> None:
        prices = [100.0 * (0.999**i) for i in range(60)]
        row = feature_row(prices)
        assert row[0] < 0
        assert row[1] < 0
        assert row[3] < 0

    def test_a_flat_series_does_not_divide_by_zero(self) -> None:
        row = feature_row([100.0] * 60)
        assert all(math.isfinite(value) for value in row)
        assert row[4] == pytest.approx(0.0)


class TestExplicitFailures:
    @pytest.mark.parametrize(
        ("call", "match"),
        [
            (lambda: simple_returns([100.0]), "simple_returns"),
            (lambda: period_return([100.0], 5), "period_return"),
            (lambda: ema([100.0], 10), "ema"),
            (lambda: rsi([100.0, 101.0], 14), "rsi"),
            (lambda: volatility_of([100.0] * 5, 20), "volatility_of"),
            (lambda: feature_row([100.0] * (FEATURE_WARMUP - 1)), "feature_row"),
        ],
    )
    def test_short_history_fails_explicitly(self, call, match: str) -> None:
        with pytest.raises(InsufficientMarketDataError, match=match):
            call()

    def test_non_positive_period_is_rejected(self) -> None:
        with pytest.raises(InsufficientMarketDataError, match="period"):
            period_return([100.0, 101.0], 0)
