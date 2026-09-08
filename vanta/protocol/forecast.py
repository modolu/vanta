"""Vanta forecast domain models (ARCHITECTURE.md §6, §14).

These are plain frozen dataclasses with no transport dependency. The Bittensor
``Synapse`` wrapper is a Phase 5 concern and must be built on top of these, not in
place of them (§10).

The protocol is deliberately tiny: ``probability_up`` and ``expected_return`` are the
only required miner outputs; everything else is optional enrichment.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from vanta.validation import (
    VantaValidationError,
    require_finite,
    require_non_negative,
    require_positive,
    require_probability,
)

__all__ = ["Direction", "Forecast", "ForecastTask", "Resolution"]


class Direction(StrEnum):
    """Realized direction of a resolved task."""

    UP = "UP"
    DOWN = "DOWN"

    @property
    def outcome(self) -> float:
        """Binary outcome ``y`` used by the Brier score: 1.0 for UP, 0.0 for DOWN (§16)."""
        return 1.0 if self is Direction.UP else 0.0


def _require_identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VantaValidationError(f"{name} must be a non-empty string, got {value!r}")
    return value


def _require_index(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VantaValidationError(f"{name} must be an int, got {type(value).__name__} {value!r}")
    if value < 0:
        raise VantaValidationError(f"{name} must be >= 0, got {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class ForecastTask:
    """A forecast request issued by the validator's task generator (§7).

    ``timestamp`` is the reference time ``T``. The task resolves at
    ``T + horizon_seconds`` against the market price then.
    """

    task_id: str
    asset: str
    reference_price: float
    timestamp: int
    horizon_seconds: int
    deadline: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _require_identifier(self.task_id, "task_id"))
        object.__setattr__(self, "asset", _require_identifier(self.asset, "asset"))
        object.__setattr__(
            self, "reference_price", require_positive(self.reference_price, "reference_price")
        )
        object.__setattr__(self, "timestamp", _require_index(self.timestamp, "timestamp"))
        object.__setattr__(
            self, "horizon_seconds", _require_index(self.horizon_seconds, "horizon_seconds")
        )
        object.__setattr__(self, "deadline", _require_index(self.deadline, "deadline"))

        if self.horizon_seconds <= 0:
            raise VantaValidationError(f"horizon_seconds must be > 0, got {self.horizon_seconds!r}")
        if self.deadline <= self.timestamp:
            raise VantaValidationError(
                f"deadline {self.deadline} must be after task timestamp {self.timestamp}"
            )
        # A submission window reaching the resolution time would let a miner observe the
        # outcome it is being asked to forecast (§27, §29).
        if self.deadline >= self.resolve_at:
            raise VantaValidationError(
                f"deadline {self.deadline} must fall before resolution time {self.resolve_at}"
            )

    @property
    def resolve_at(self) -> int:
        """Unix timestamp at which this task's outcome becomes known."""
        return self.timestamp + self.horizon_seconds


@dataclass(frozen=True, slots=True)
class Forecast:
    """A miner's response to a :class:`ForecastTask` (§6)."""

    task_id: str
    miner_uid: int
    probability_up: float
    expected_return: float
    expected_volatility: float | None = None
    confidence: float | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _require_identifier(self.task_id, "task_id"))
        object.__setattr__(self, "miner_uid", _require_index(self.miner_uid, "miner_uid"))
        object.__setattr__(
            self, "probability_up", require_probability(self.probability_up, "probability_up")
        )
        object.__setattr__(
            self, "expected_return", require_finite(self.expected_return, "expected_return")
        )
        if self.expected_volatility is not None:
            object.__setattr__(
                self,
                "expected_volatility",
                require_non_negative(self.expected_volatility, "expected_volatility"),
            )
        if self.confidence is not None:
            object.__setattr__(
                self, "confidence", require_probability(self.confidence, "confidence")
            )

    @property
    def probability_down(self) -> float:
        return 1.0 - self.probability_up


@dataclass(frozen=True, slots=True)
class Resolution:
    """Ground truth for a task, derived from the realized market price (§14)."""

    task_id: str
    reference_price: float
    resolution_price: float
    resolved_at: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _require_identifier(self.task_id, "task_id"))
        object.__setattr__(
            self, "reference_price", require_positive(self.reference_price, "reference_price")
        )
        object.__setattr__(
            self, "resolution_price", require_positive(self.resolution_price, "resolution_price")
        )
        object.__setattr__(self, "resolved_at", _require_index(self.resolved_at, "resolved_at"))

    @classmethod
    def from_task(
        cls, task: ForecastTask, resolution_price: float, resolved_at: int | None = None
    ) -> Resolution:
        """Resolve ``task`` against ``resolution_price``, inheriting its reference price."""
        return cls(
            task_id=task.task_id,
            reference_price=task.reference_price,
            resolution_price=resolution_price,
            resolved_at=task.resolve_at if resolved_at is None else resolved_at,
        )

    @property
    def realized_return(self) -> float:
        """Simple return over the horizon: ``(resolution - reference) / reference``."""
        return (self.resolution_price - self.reference_price) / self.reference_price

    @property
    def direction(self) -> Direction:
        """Realized direction.

        AMBIGUITY (§14): the architecture defines UP and DOWN but is silent on an exactly
        flat market. We treat strictly positive returns as UP, so a zero return resolves
        DOWN. Confirm before this reaches testnet.
        """
        return Direction.UP if self.realized_return > 0.0 else Direction.DOWN

    @property
    def outcome(self) -> float:
        """Binary outcome ``y`` for the Brier score (§16)."""
        return self.direction.outcome
