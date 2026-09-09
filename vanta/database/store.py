"""The validator's persistence interface (ARCHITECTURE.md §37, §43).

A live validator issues a task at ``T`` and cannot resolve it until ``T + horizon``. Its
in-flight state must therefore survive a restart, or every task inside that window is
silently lost along with the forecasts already collected for it.

This module defines *what* the validator needs to store, not *how*. The validator
depends only on :class:`ValidatorStore`; the SQLite implementation lives in
:mod:`vanta.database.sqlite` and a PostgreSQL one can be added later without the
validator changing. Nothing here assumes SQLite semantics — no ``INSERT OR REPLACE``,
no implicit types, no autocommit behaviour leaks through the interface.

The store records what happened. It computes nothing: no scores, no reputation, no
weights. Deriving mechanism values here would put a second, divergent implementation of
the mechanism behind a database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from vanta.protocol.forecast import Forecast, ForecastTask, Resolution
from vanta.validator.scorer import ForecastScore

__all__ = ["PendingTask", "StoredForecast", "ValidatorStore"]


@dataclass(frozen=True, slots=True)
class StoredForecast:
    """A forecast as persisted: the forecast itself plus the hotkey that produced it.

    The hotkey is stored alongside the uid because reputation follows the hotkey, and a
    uid read back after a deregistration may now belong to someone else.
    """

    forecast: Forecast
    hotkey: str


@dataclass(frozen=True, slots=True)
class PendingTask:
    """An unresolved task recovered after a restart, with the forecasts already held."""

    task: ForecastTask
    forecasts: tuple[StoredForecast, ...]


class ValidatorStore(ABC):
    """Durable validator state: tasks, forecasts, resolutions and scores.

    Implementations must be safe to call from a single validator process and must make
    each recording operation atomic. Every method is idempotent on its primary key: the
    validator may re-record a task or forecast after a crash mid-round without
    duplicating it or raising.
    """

    @abstractmethod
    def record_task(self, task: ForecastTask) -> None:
        """Persist an issued task. Idempotent on ``task_id``."""

    @abstractmethod
    def record_forecasts(self, task_id: str, forecasts: tuple[StoredForecast, ...]) -> None:
        """Persist the forecasts collected for a task.

        Idempotent on ``(task_id, hotkey)``: re-recording replaces the stored forecast
        rather than adding a second row for the same miner.
        """

    @abstractmethod
    def record_resolution(self, resolution: Resolution) -> None:
        """Persist ground truth, marking the task resolved. Idempotent on ``task_id``.

        A void resolution (§14) is stored too: the task is settled and must not be
        retried, even though nothing is scored against it.
        """

    @abstractmethod
    def record_scores(self, task_id: str, scores: dict[str, ForecastScore]) -> None:
        """Persist the per-miner scores for a resolved task, keyed by hotkey."""

    @abstractmethod
    def pending_tasks(self, *, resolvable_at: int | None = None) -> tuple[PendingTask, ...]:
        """Unresolved tasks, oldest first, each with the forecasts already collected.

        This is what makes a restart safe: the validator reloads its in-flight window
        and resumes resolving it.

        Args:
            resolvable_at: when given, only tasks whose resolution time has already
                passed at this instant are returned.
        """

    @abstractmethod
    def has_task(self, task_id: str) -> bool:
        """Whether a task has already been issued and stored."""

    @abstractmethod
    def close(self) -> None:
        """Release the underlying resources."""

    def __enter__(self) -> ValidatorStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
