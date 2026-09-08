from __future__ import annotations

import math

import pytest

from vanta.consensus.aggregator import consensus_probability
from vanta.validation import VantaValidationError

# §30's worked example.
PROBABILITIES = {0: 0.72, 1: 0.55, 2: 0.81, 3: 0.40}
RELIABILITIES = {0: 0.84, 1: 0.61, 2: 0.76, 3: 0.23}


def test_matches_the_reliability_weighted_formula() -> None:
    expected = sum(PROBABILITIES[uid] * RELIABILITIES[uid] for uid in PROBABILITIES) / sum(
        RELIABILITIES.values()
    )
    result = consensus_probability(PROBABILITIES, RELIABILITIES)
    assert result.probability_up == pytest.approx(expected)


def test_architecture_example_lands_near_sixty_seven_percent() -> None:
    # §30 quotes "67% UP" for these inputs.
    result = consensus_probability(PROBABILITIES, RELIABILITIES)
    assert result.probability_up == pytest.approx(0.67, abs=0.02)


def test_reliable_miners_pull_the_consensus_more_than_unreliable_ones() -> None:
    weighted = consensus_probability({0: 0.9, 1: 0.1}, {0: 0.9, 1: 0.1})
    flipped = consensus_probability({0: 0.9, 1: 0.1}, {0: 0.1, 1: 0.9})
    assert weighted.probability_up > 0.5
    assert flipped.probability_up < 0.5


def test_differs_from_a_naive_average() -> None:
    naive = sum(PROBABILITIES.values()) / len(PROBABILITIES)
    result = consensus_probability(PROBABILITIES, RELIABILITIES)
    assert result.probability_up != pytest.approx(naive)


def test_a_single_unreliable_outlier_barely_moves_consensus() -> None:
    # §40 test 7.
    base = consensus_probability({0: 0.70, 1: 0.68, 2: 0.72}, {0: 0.8, 1: 0.8, 2: 0.8})
    with_outlier = consensus_probability(
        {0: 0.70, 1: 0.68, 2: 0.72, 3: 0.02}, {0: 0.8, 1: 0.8, 2: 0.8, 3: 0.01}
    )
    assert abs(with_outlier.probability_up - base.probability_up) < 0.02


def test_zero_reliability_miner_is_ignored() -> None:
    result = consensus_probability({0: 0.9, 1: 0.1}, {0: 0.5, 1: 0.0})
    assert result.probability_up == pytest.approx(0.9)


def test_agreement_produces_low_dispersion() -> None:
    agreeing = consensus_probability({0: 0.70, 1: 0.71, 2: 0.69}, {0: 0.8, 1: 0.8, 2: 0.8})
    disagreeing = consensus_probability({0: 0.95, 1: 0.50, 2: 0.05}, {0: 0.8, 1: 0.8, 2: 0.8})
    assert agreeing.dispersion < disagreeing.dispersion
    assert agreeing.dispersion == pytest.approx(0.008165, abs=1e-5)


def test_reports_participation_and_total_weight() -> None:
    result = consensus_probability(PROBABILITIES, RELIABILITIES)
    assert result.contributing_miners == 4
    assert result.total_weight == pytest.approx(sum(RELIABILITIES.values()))


def test_falls_back_to_an_equal_weighted_mean_when_nobody_is_reliable_yet() -> None:
    result = consensus_probability({0: 0.8, 1: 0.4}, {0: 0.0, 1: 0.0})
    assert result.probability_up == pytest.approx(0.6)
    assert result.total_weight == 0.0


def test_result_stays_within_the_unit_interval() -> None:
    result = consensus_probability({0: 1.0, 1: 0.0}, {0: 0.3, 1: 0.7})
    assert 0.0 <= result.probability_up <= 1.0


def test_empty_forecasts_are_rejected() -> None:
    with pytest.raises(VantaValidationError, match="zero forecasts"):
        consensus_probability({}, {})


def test_missing_reliability_is_an_error_not_a_silent_exclusion() -> None:
    with pytest.raises(VantaValidationError, match="no reliability supplied for miner 1"):
        consensus_probability({0: 0.5, 1: 0.5}, {0: 0.8})


@pytest.mark.parametrize("bad", [-0.1, 1.1, math.nan, math.inf])
def test_invalid_probabilities_are_rejected(bad: float) -> None:
    with pytest.raises(VantaValidationError, match="probability_up"):
        consensus_probability({0: bad}, {0: 0.8})


@pytest.mark.parametrize("bad", [-0.5, math.nan, math.inf])
def test_invalid_reliabilities_are_rejected(bad: float) -> None:
    with pytest.raises(VantaValidationError, match="reliability"):
        consensus_probability({0: 0.5}, {0: bad})


def test_is_deterministic() -> None:
    assert consensus_probability(PROBABILITIES, RELIABILITIES) == consensus_probability(
        PROBABILITIES, RELIABILITIES
    )
