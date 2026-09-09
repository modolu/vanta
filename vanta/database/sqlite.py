"""SQLite implementation of :class:`~vanta.database.store.ValidatorStore`.

The Phase 5 store. The schema is written to be portable — plain SQL types, explicit
primary keys, no SQLite-only syntax in the DDL — but portability is asserted nowhere and
proven by nothing until a PostgreSQL implementation exists and is tested against a real
server. Treat this as "SQLite today, structured so PostgreSQL is a small step", not as
"already PostgreSQL-compatible".

Where SQLite genuinely differs from PostgreSQL, the difference is confined to this
module: the ``?`` placeholder style, the ``INSERT ... ON CONFLICT DO UPDATE`` upsert
spelling (which PostgreSQL happens to share), and REAL/INTEGER affinity. The
:class:`ValidatorStore` interface exposes none of it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from vanta.database.store import PendingTask, StoredForecast, ValidatorStore
from vanta.log import get_logger
from vanta.protocol.forecast import Forecast, ForecastTask, Resolution
from vanta.validator.scorer import ForecastScore

__all__ = ["SqliteValidatorStore"]

logger = get_logger(__name__)

# Column types are chosen to mean the same thing under PostgreSQL: TEXT, INTEGER (int8)
# and DOUBLE PRECISION. `resolved_at IS NULL` is the pending-task marker.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id          TEXT PRIMARY KEY,
    asset            TEXT    NOT NULL,
    reference_price  DOUBLE PRECISION NOT NULL,
    timestamp        INTEGER NOT NULL,
    horizon_seconds  INTEGER NOT NULL,
    deadline         INTEGER NOT NULL,
    resolve_at       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS forecasts (
    task_id             TEXT NOT NULL,
    hotkey              TEXT NOT NULL,
    miner_uid           INTEGER NOT NULL,
    probability_up      DOUBLE PRECISION NOT NULL,
    expected_return     DOUBLE PRECISION NOT NULL,
    expected_volatility DOUBLE PRECISION,
    confidence          DOUBLE PRECISION,
    model_version       TEXT,
    PRIMARY KEY (task_id, hotkey)
);

CREATE TABLE IF NOT EXISTS resolutions (
    task_id          TEXT PRIMARY KEY,
    reference_price  DOUBLE PRECISION NOT NULL,
    resolution_price DOUBLE PRECISION NOT NULL,
    resolved_at      INTEGER NOT NULL,
    is_void          INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS scores (
    task_id               TEXT NOT NULL,
    hotkey                TEXT NOT NULL,
    miner_uid             INTEGER NOT NULL,
    brier                 DOUBLE PRECISION NOT NULL,
    probability_quality   DOUBLE PRECISION NOT NULL,
    return_score          DOUBLE PRECISION NOT NULL,
    calibration_component DOUBLE PRECISION NOT NULL,
    total_score           DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (task_id, hotkey)
);

CREATE INDEX IF NOT EXISTS idx_forecasts_task ON forecasts (task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_resolve_at ON tasks (resolve_at);
"""


class SqliteValidatorStore(ValidatorStore):
    """Validator state in a SQLite database file (or ``:memory:`` for tests)."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._path)
        self._connection.row_factory = sqlite3.Row
        # Durability across a crash mid-round is the entire point of this store.
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    @classmethod
    def from_url(cls, database_url: str) -> SqliteValidatorStore:
        """Build a store from a ``sqlite:///path`` URL.

        Raises:
            ValueError: for any non-SQLite URL. A PostgreSQL URL is a configuration
                error today rather than something to silently downgrade.
        """
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ValueError(
                f"SqliteValidatorStore needs a {prefix!r} URL, got {database_url!r}; "
                "no other backend is implemented yet"
            )
        return cls(database_url[len(prefix) :] or ":memory:")

    # --- writes -------------------------------------------------------------------

    def record_task(self, task: ForecastTask) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO tasks
                    (task_id, asset, reference_price, timestamp, horizon_seconds,
                     deadline, resolve_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (task_id) DO NOTHING
                """,
                (
                    task.task_id,
                    task.asset,
                    task.reference_price,
                    task.timestamp,
                    task.horizon_seconds,
                    task.deadline,
                    task.resolve_at,
                ),
            )

    def record_forecasts(self, task_id: str, forecasts: tuple[StoredForecast, ...]) -> None:
        if not forecasts:
            return
        rows = [
            (
                task_id,
                stored.hotkey,
                stored.forecast.miner_uid,
                stored.forecast.probability_up,
                stored.forecast.expected_return,
                stored.forecast.expected_volatility,
                stored.forecast.confidence,
                stored.forecast.model_version,
            )
            for stored in forecasts
        ]
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO forecasts
                    (task_id, hotkey, miner_uid, probability_up, expected_return,
                     expected_volatility, confidence, model_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (task_id, hotkey) DO UPDATE SET
                    miner_uid = excluded.miner_uid,
                    probability_up = excluded.probability_up,
                    expected_return = excluded.expected_return,
                    expected_volatility = excluded.expected_volatility,
                    confidence = excluded.confidence,
                    model_version = excluded.model_version
                """,
                rows,
            )

    def record_resolution(self, resolution: Resolution) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO resolutions
                    (task_id, reference_price, resolution_price, resolved_at, is_void)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (task_id) DO UPDATE SET
                    reference_price = excluded.reference_price,
                    resolution_price = excluded.resolution_price,
                    resolved_at = excluded.resolved_at,
                    is_void = excluded.is_void
                """,
                (
                    resolution.task_id,
                    resolution.reference_price,
                    resolution.resolution_price,
                    resolution.resolved_at,
                    int(resolution.is_void),
                ),
            )

    def record_scores(self, task_id: str, scores: dict[str, ForecastScore]) -> None:
        if not scores:
            return
        rows = [
            (
                task_id,
                hotkey,
                score.miner_uid,
                score.brier,
                score.probability_quality,
                score.return_score,
                score.calibration_component,
                score.total_score,
            )
            for hotkey, score in scores.items()
        ]
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO scores
                    (task_id, hotkey, miner_uid, brier, probability_quality, return_score,
                     calibration_component, total_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (task_id, hotkey) DO UPDATE SET
                    miner_uid = excluded.miner_uid,
                    brier = excluded.brier,
                    probability_quality = excluded.probability_quality,
                    return_score = excluded.return_score,
                    calibration_component = excluded.calibration_component,
                    total_score = excluded.total_score
                """,
                rows,
            )

    # --- reads --------------------------------------------------------------------

    def has_task(self, task_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        return row is not None

    def pending_tasks(self, *, resolvable_at: int | None = None) -> tuple[PendingTask, ...]:
        sql = """
            SELECT t.*
            FROM tasks t
            LEFT JOIN resolutions r ON r.task_id = t.task_id
            WHERE r.task_id IS NULL
        """
        params: list[object] = []
        if resolvable_at is not None:
            sql += " AND t.resolve_at <= ?"
            params.append(int(resolvable_at))
        sql += " ORDER BY t.timestamp ASC, t.task_id ASC"

        task_rows = self._connection.execute(sql, params).fetchall()
        if not task_rows:
            return ()

        forecasts = self._forecasts_for({row["task_id"] for row in task_rows})
        return tuple(
            PendingTask(
                task=_task_from_row(row),
                forecasts=tuple(forecasts.get(row["task_id"], ())),
            )
            for row in task_rows
        )

    def _forecasts_for(self, task_ids: Iterable[str]) -> dict[str, list[StoredForecast]]:
        ids = list(task_ids)
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self._connection.execute(
            f"SELECT * FROM forecasts WHERE task_id IN ({placeholders}) ORDER BY hotkey ASC",
            ids,
        ).fetchall()
        grouped: dict[str, list[StoredForecast]] = {}
        for row in rows:
            grouped.setdefault(row["task_id"], []).append(
                StoredForecast(
                    forecast=Forecast(
                        task_id=row["task_id"],
                        miner_uid=row["miner_uid"],
                        probability_up=row["probability_up"],
                        expected_return=row["expected_return"],
                        expected_volatility=row["expected_volatility"],
                        confidence=row["confidence"],
                        model_version=row["model_version"],
                    ),
                    hotkey=row["hotkey"],
                )
            )
        return grouped

    def close(self) -> None:
        self._connection.close()


def _task_from_row(row: sqlite3.Row) -> ForecastTask:
    """Rebuild a task, re-running every protocol invariant on the way out of storage."""
    return ForecastTask(
        task_id=row["task_id"],
        asset=row["asset"],
        reference_price=row["reference_price"],
        timestamp=row["timestamp"],
        horizon_seconds=row["horizon_seconds"],
        deadline=row["deadline"],
    )
