from __future__ import annotations

import math

import pytest

from vanta.validation import (
    VantaValidationError,
    require_finite,
    require_non_negative,
    require_positive,
    require_probability,
)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nan_and_infinities_are_rejected(bad: float) -> None:
    with pytest.raises(VantaValidationError, match="finite"):
        require_finite(bad, "value")


@pytest.mark.parametrize("bad", [True, False])
def test_bools_are_not_numbers(bad: bool) -> None:
    with pytest.raises(VantaValidationError, match="real number"):
        require_finite(bad, "value")


@pytest.mark.parametrize("bad", ["0.5", None, [1.0], {"a": 1}])
def test_non_numeric_types_are_rejected(bad: object) -> None:
    with pytest.raises(VantaValidationError, match="real number"):
        require_finite(bad, "value")


def test_ints_are_accepted_as_floats() -> None:
    assert require_finite(3, "value") == 3.0
    assert isinstance(require_finite(3, "value"), float)


@pytest.mark.parametrize("bad", [-0.001, 1.001, 2.0, -1.0])
def test_probabilities_outside_the_unit_interval_are_rejected(bad: float) -> None:
    with pytest.raises(VantaValidationError, match=r"\[0, 1\]"):
        require_probability(bad, "p")


@pytest.mark.parametrize("good", [0.0, 0.5, 1.0])
def test_unit_interval_endpoints_are_valid(good: float) -> None:
    assert require_probability(good, "p") == good


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_require_positive_rejects_zero_and_negatives(bad: float) -> None:
    with pytest.raises(VantaValidationError, match="> 0"):
        require_positive(bad, "scale")


def test_require_non_negative_allows_zero_but_not_negatives() -> None:
    assert require_non_negative(0.0, "w") == 0.0
    with pytest.raises(VantaValidationError, match=">= 0"):
        require_non_negative(-0.5, "w")


def test_error_message_names_the_offending_field() -> None:
    with pytest.raises(VantaValidationError, match="expected_return"):
        require_finite(math.nan, "expected_return")
