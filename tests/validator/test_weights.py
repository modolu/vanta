from __future__ import annotations

import math

import pytest

from vanta.validation import VantaValidationError
from vanta.validator.weights import DEFAULT_GAMMA, compute_weights

# §21's worked example.
EXAMPLE_SCORES = {0: 0.81, 1: 0.72, 2: 0.54, 3: 0.31, 4: 0.15}


def test_weights_sum_to_one() -> None:
    weights = compute_weights(EXAMPLE_SCORES)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_every_miner_receives_a_weight() -> None:
    weights = compute_weights(EXAMPLE_SCORES)
    assert set(weights) == set(EXAMPLE_SCORES)


def test_higher_reputation_earns_more_weight() -> None:
    weights = compute_weights(EXAMPLE_SCORES)
    ordered = [weights[uid] for uid, _ in sorted(EXAMPLE_SCORES.items(), key=lambda kv: -kv[1])]
    assert ordered == sorted(ordered, reverse=True)


def test_reproduces_the_architecture_example_within_a_point() -> None:
    # §21 quotes roughly 35 / 28 / 20 / 11 / 6 percent.
    weights = compute_weights(EXAMPLE_SCORES, gamma=DEFAULT_GAMMA)
    assert weights[0] == pytest.approx(0.35, abs=0.015)
    assert weights[1] == pytest.approx(0.28, abs=0.02)
    assert weights[2] == pytest.approx(0.20, abs=0.015)
    assert weights[3] == pytest.approx(0.11, abs=0.015)
    assert weights[4] == pytest.approx(0.06, abs=0.02)


def test_is_not_winner_take_all() -> None:
    # §22: competent secondary models must still survive.
    weights = compute_weights(EXAMPLE_SCORES)
    assert weights[0] < 0.5
    assert all(weight > 0.0 for weight in weights.values())


def test_gamma_above_one_widens_the_gap() -> None:
    linear = compute_weights(EXAMPLE_SCORES, gamma=1.0)
    emphasized = compute_weights(EXAMPLE_SCORES, gamma=3.0)
    assert emphasized[0] > linear[0]
    assert emphasized[4] < linear[4]
    assert sum(emphasized.values()) == pytest.approx(1.0)


def test_equal_scores_produce_equal_weights() -> None:
    weights = compute_weights({0: 0.5, 1: 0.5, 2: 0.5})
    assert all(weight == pytest.approx(1 / 3) for weight in weights.values())


def test_zero_score_earns_zero_weight() -> None:
    weights = compute_weights({0: 0.8, 1: 0.0})
    assert weights[1] == 0.0
    assert weights[0] == pytest.approx(1.0)


def test_all_zero_scores_fall_back_to_uniform_weights() -> None:
    weights = compute_weights({0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0})
    assert sum(weights.values()) == pytest.approx(1.0)
    assert all(weight == pytest.approx(0.25) for weight in weights.values())


def test_provisional_scale_reduces_new_miner_weight() -> None:
    full = compute_weights({0: 0.8, 1: 0.8})
    limited = compute_weights({0: 0.8, 1: 0.8}, provisional={1}, provisional_scale=0.25)
    assert limited[1] < full[1]
    assert limited[0] > full[0]
    assert sum(limited.values()) == pytest.approx(1.0)


def test_provisional_scale_defaults_to_no_penalty() -> None:
    assert compute_weights({0: 0.8, 1: 0.8}, provisional={1}) == compute_weights({0: 0.8, 1: 0.8})


def test_empty_scores_are_rejected() -> None:
    with pytest.raises(VantaValidationError, match="empty"):
        compute_weights({})


@pytest.mark.parametrize("bad", [-0.1, math.nan, math.inf])
def test_invalid_scores_are_rejected(bad: float) -> None:
    with pytest.raises(VantaValidationError, match="score for miner"):
        compute_weights({0: 0.5, 1: bad})


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan])
def test_invalid_gamma_is_rejected(bad: float) -> None:
    with pytest.raises(VantaValidationError, match="gamma"):
        compute_weights(EXAMPLE_SCORES, gamma=bad)


def test_invalid_uid_is_rejected() -> None:
    with pytest.raises(VantaValidationError, match="uid"):
        compute_weights({-1: 0.5})


def test_is_deterministic() -> None:
    assert compute_weights(EXAMPLE_SCORES) == compute_weights(EXAMPLE_SCORES)
