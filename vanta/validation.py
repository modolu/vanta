"""Explicit, deterministic input validation shared by the scoring mechanism.

Every numeric entering the mechanism passes through here. The rules are strict on
purpose: a NaN reaching the scorer would propagate silently into reputation, weights
and consensus, and honest validators must agree bit-for-bit on the same task
universe (ARCHITECTURE.md §24).
"""

from __future__ import annotations

import math
from typing import Any

__all__ = [
    "VantaValidationError",
    "require_finite",
    "require_non_negative",
    "require_positive",
    "require_probability",
]


class VantaValidationError(ValueError):
    """Raised when an input violates a mechanism invariant."""


def require_finite(value: Any, name: str) -> float:
    """Return ``value`` as a float, rejecting non-numerics, bools, NaN and infinities."""
    if isinstance(value, bool):
        raise VantaValidationError(f"{name} must be a real number, got bool {value!r}")
    if not isinstance(value, (int, float)):
        raise VantaValidationError(
            f"{name} must be a real number, got {type(value).__name__} {value!r}"
        )
    numeric = float(value)
    if not math.isfinite(numeric):
        raise VantaValidationError(f"{name} must be finite, got {value!r}")
    return numeric


def require_probability(value: Any, name: str) -> float:
    """Return ``value`` as a float in the closed unit interval."""
    numeric = require_finite(value, name)
    if not 0.0 <= numeric <= 1.0:
        raise VantaValidationError(f"{name} must lie in [0, 1], got {numeric!r}")
    return numeric


def require_positive(value: Any, name: str) -> float:
    """Return ``value`` as a strictly positive float."""
    numeric = require_finite(value, name)
    if numeric <= 0.0:
        raise VantaValidationError(f"{name} must be > 0, got {numeric!r}")
    return numeric


def require_non_negative(value: Any, name: str) -> float:
    """Return ``value`` as a non-negative float."""
    numeric = require_finite(value, name)
    if numeric < 0.0:
        raise VantaValidationError(f"{name} must be >= 0, got {numeric!r}")
    return numeric
