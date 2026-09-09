"""Validator task generation (ARCHITECTURE.md §7).

Chooses the asset and horizon, fixes the reference price, and stamps a unique task with
a submission deadline. This is the same task construction the Phase 4 replay performed
inline; it is extracted here so the live validator and the simulation build tasks by
identical rules.

No chain code and no scoring live here.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from vanta.market.resolution import ResolutionEngine
from vanta.protocol.forecast import ForecastTask
from vanta.validation import VantaValidationError

__all__ = ["TaskGenerator", "task_identifier"]


def task_identifier(asset: str, horizon_seconds: int, timestamp: int) -> str:
    """The canonical task id.

    Deterministic on purpose (§24): two honest validators generating a task for the same
    asset, horizon and instant produce the same id, which is what makes their scoring
    universes comparable. It carries no randomness and no validator identity.
    """
    return f"{asset}-{horizon_seconds}s-{timestamp}"


@dataclass(frozen=True, slots=True)
class TaskGenerator:
    """Builds forecast tasks against a live market feed."""

    resolution: ResolutionEngine
    asset: str
    horizon_seconds: int
    submission_window_seconds: int
    clock: Callable[[], float] = time.time

    def __post_init__(self) -> None:
        if self.horizon_seconds <= 0:
            raise VantaValidationError(f"horizon_seconds must be > 0, got {self.horizon_seconds}")
        if self.submission_window_seconds <= 0:
            raise VantaValidationError(
                f"submission_window_seconds must be > 0, got {self.submission_window_seconds}"
            )
        if self.submission_window_seconds >= self.horizon_seconds:
            raise VantaValidationError(
                f"submission_window_seconds ({self.submission_window_seconds}) must be < "
                f"horizon_seconds ({self.horizon_seconds}); a window reaching the resolution "
                "time would let a miner observe the outcome (§27, §29)"
            )

    def generate(self, timestamp: int | None = None) -> ForecastTask:
        """Create the next task, pricing it at ``timestamp`` (default: now).

        The reference price is fetched once and frozen into the task. It is never
        refetched at resolution, so the realized return always measures the move the
        miners were actually asked about.

        Raises:
            MarketDataError: if no usable reference price exists at ``timestamp``.
            VantaValidationError: if the resulting task violates a protocol invariant.
        """
        at = int(self.clock()) if timestamp is None else int(timestamp)
        reference_price = self.resolution.reference_price(self.asset, at)
        return ForecastTask(
            task_id=task_identifier(self.asset, self.horizon_seconds, at),
            asset=self.asset,
            reference_price=reference_price,
            timestamp=at,
            horizon_seconds=self.horizon_seconds,
            deadline=at + self.submission_window_seconds,
        )
