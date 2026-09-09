"""The Bittensor validator neuron (ARCHITECTURE.md §7, §14-§21, §39).

One iteration of the validator lifecycle:

    sync metagraph -> generate task -> query miners -> persist
                   -> (later) resolve -> score -> update reputation
                   -> compute weights -> submit

Every mechanism value comes from the modules the historical replay already proved:
:func:`~vanta.validator.scorer.score_forecast`, :class:`~vanta.validator.reputation.
MinerReputation` and :func:`~vanta.validator.weights.compute_weights`. This module
sequences them and moves data; it contains no scoring rule of its own.

Two behaviours differ deliberately from the replay, because a live network is not a
recorded one:

* The replay drops a task unless every engine answers, keeping the task universe
  identical across miners. Live, miners time out individually, so a miner is scored on
  the tasks it actually answered and simply accrues no state for the ones it missed.
* Resolution is decoupled from issuance. A task issued at ``T`` is resolved on a later
  pass, once ``T + horizon`` has passed — reloaded from storage if the process restarted
  in between.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from vanta.database.store import PendingTask, StoredForecast, ValidatorStore
from vanta.log import get_logger
from vanta.market.errors import MarketDataError
from vanta.market.resolution import ResolutionEngine
from vanta.neurons.chain import ChainError, NeuronRecord, SubnetView, WeightSubmitter
from vanta.protocol.forecast import ForecastTask, Resolution, VoidResolutionError
from vanta.validator.collector import ForecastCollector, MinerQuery
from vanta.validator.scorer import ForecastScore, score_forecast
from vanta.validator.task_generator import TaskGenerator
from vanta.validator.weight_adapter import MinerRegistry

__all__ = ["ResolutionOutcome", "RoundReport", "Validator", "ValidatorConfig"]

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ValidatorConfig:
    """Operational cadence. None of these are mechanism parameters."""

    netuid: int
    asset: str
    horizon_seconds: int
    # How often to issue a task. Defaults to one horizon, matching the replay's spacing.
    task_interval_seconds: int
    # Minimum gap between weight submissions. The chain enforces its own rate limit; this
    # keeps the validator from hammering it.
    weight_interval_seconds: int = 360
    # A validator never queries itself.
    self_hotkey: str | None = None

    def __post_init__(self) -> None:
        if self.task_interval_seconds <= 0:
            raise ValueError("task_interval_seconds must be > 0")
        if self.weight_interval_seconds <= 0:
            raise ValueError("weight_interval_seconds must be > 0")


@dataclass(frozen=True, slots=True)
class ResolutionOutcome:
    """What happened when one pending task was settled."""

    task_id: str
    resolved: bool
    void: bool = False
    scored: int = 0
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RoundReport:
    """Everything one validator iteration did. Returned for logging and for tests."""

    task_id: str | None = None
    queried: int = 0
    collected: int = 0
    rejected: dict[int, str] | None = None
    resolutions: tuple[ResolutionOutcome, ...] = ()
    weights_submitted: dict[int, float] | None = None
    weight_result: str | None = None
    errors: tuple[str, ...] = ()


class Validator:
    """The validator neuron. Chain access arrives as protocols, never as SDK objects."""

    def __init__(
        self,
        *,
        config: ValidatorConfig,
        generator: TaskGenerator,
        collector: ForecastCollector,
        resolution: ResolutionEngine,
        registry: MinerRegistry,
        store: ValidatorStore,
        view: SubnetView | None = None,
        submitter: WeightSubmitter | None = None,
        static_miners: Sequence[MinerQuery] = (),
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._generator = generator
        self._collector = collector
        self._resolution = resolution
        self._registry = registry
        self._store = store
        self._view = view
        self._submitter = submitter
        self._static_miners = tuple(static_miners)
        self._clock = clock
        self._last_weights_at: float | None = None

    # --- metagraph ------------------------------------------------------------------

    def sync(self) -> list[NeuronRecord]:
        """Read the current neuron set and reconcile reputation against it.

        A hotkey that has left the subnet loses its stored reputation here; a uid whose
        occupant changed is left to start fresh, because reputation is keyed by hotkey
        and the newcomer has no record.
        """
        if self._view is None:
            return []
        neurons = self._view.neurons(self._config.netuid)
        self._registry.sync(neurons)
        self._registry.observe(neurons)
        return neurons

    def miners(self, neurons: Sequence[NeuronRecord]) -> list[MinerQuery]:
        """The queryable miners: registered, serving an endpoint, and not us."""
        if self._view is None:
            return list(self._static_miners)
        queries: list[MinerQuery] = []
        for neuron in neurons:
            if not neuron.is_servable:
                continue
            if self._config.self_hotkey is not None and neuron.hotkey == self._config.self_hotkey:
                continue
            queries.append(
                MinerQuery(uid=neuron.uid, hotkey=neuron.hotkey, url=f"http://{neuron.axon}")
            )
        return queries

    # --- issuing --------------------------------------------------------------------

    def issue_task(self, miners: Sequence[MinerQuery]) -> tuple[ForecastTask | None, dict]:
        """Generate a task, query the miners, and persist whatever came back."""
        if not miners:
            logger.info("no servable miners this round; skipping task issuance")
            return None, {}

        task = self._generator.generate()
        # Persisted before any miner is asked: a crash between the query and the write
        # would otherwise lose a task that miners have already answered.
        self._store.record_task(task)

        result = self._collector.collect(task, miners)
        stored = tuple(
            StoredForecast(forecast=forecast, hotkey=result.hotkeys[uid])
            for uid, forecast in result.forecasts.items()
        )
        self._store.record_forecasts(task.task_id, stored)

        logger.info(
            "task %s: queried %d miners, collected %d forecasts (%d rejected)",
            task.task_id,
            len(miners),
            len(stored),
            len(result.rejected),
        )
        for uid, reason in result.rejected.items():
            logger.debug("uid %d not counted for %s: %s", uid, task.task_id, reason)
        return task, dict(result.rejected)

    # --- resolving ------------------------------------------------------------------

    def resolve_due(self, now: int | None = None) -> tuple[ResolutionOutcome, ...]:
        """Resolve and score every pending task whose horizon has elapsed.

        Reloaded from storage, so tasks issued before a restart are picked up here.
        """
        at = int(self._clock()) if now is None else now
        pending = self._store.pending_tasks(resolvable_at=at)
        return tuple(self._settle(entry) for entry in pending)

    def _settle(self, entry: PendingTask) -> ResolutionOutcome:
        task = entry.task
        try:
            resolution = self._resolution.resolve(task)
        except MarketDataError as exc:
            # Left pending on purpose: a venue gap now may be filled on a later pass.
            logger.warning("cannot resolve %s yet: %s", task.task_id, exc)
            return ResolutionOutcome(task_id=task.task_id, resolved=False, reason=str(exc))

        self._store.record_resolution(resolution)

        if resolution.is_void:
            # §14 (LOCKED): an exactly flat market voids the directional outcome. No
            # miner state is touched — not scores, not calibration, not reputation.
            logger.info("task %s resolved exactly flat; void", task.task_id)
            return ResolutionOutcome(task_id=task.task_id, resolved=True, void=True)

        try:
            return_scale = self._resolution.return_scale(
                task.asset, task.timestamp, task.horizon_seconds
            )
        except (MarketDataError, ValueError) as exc:
            logger.warning("no return scale for %s: %s", task.task_id, exc)
            return ResolutionOutcome(task_id=task.task_id, resolved=True, reason=str(exc))

        scores = self._score_all(entry, resolution, return_scale)
        self._store.record_scores(task.task_id, scores)
        logger.info(
            "task %s resolved: realized_return=%+.6f, scored %d miners",
            task.task_id,
            resolution.realized_return,
            len(scores),
        )
        return ResolutionOutcome(task_id=task.task_id, resolved=True, scored=len(scores))

    def _score_all(
        self, entry: PendingTask, resolution: Resolution, return_scale: float
    ) -> dict[str, ForecastScore]:
        """Score every stored forecast and fold each into its miner's reputation.

        The calibration term is read *before* the forecast is recorded, so a forecast
        never contributes to its own calibration component (§18).
        """
        outcome = resolution.require_outcome()
        scores: dict[str, ForecastScore] = {}

        # Deterministic order: honest validators scoring the same task must agree (§24),
        # and reputation is order-sensitive state.
        for stored in sorted(entry.forecasts, key=lambda item: item.hotkey):
            forecast = stored.forecast
            reputation = self._registry.reputation_for(stored.hotkey, forecast.miner_uid)
            try:
                score = score_forecast(
                    forecast,
                    resolution,
                    return_scale=return_scale,
                    calibration_component=reputation.calibration_component,
                )
            except VoidResolutionError:  # pragma: no cover - void handled before we get here
                continue
            reputation.record(score.total_score, forecast.probability_up, outcome)
            scores[stored.hotkey] = score
        return scores

    # --- weights --------------------------------------------------------------------

    def submit_weights(
        self, neurons: Sequence[NeuronRecord], *, force: bool = False
    ) -> tuple[dict[int, float] | None, str | None]:
        """Convert reputation into a weight vector and submit it.

        Returns the submitted vector and the chain's result, or ``(None, reason)`` when
        nothing was submitted. A submission failure is logged and reported; it never
        raises out of the loop and never mutates reputation.
        """
        if self._submitter is None:
            return None, "no weight submitter configured"

        now = self._clock()
        if (
            not force
            and self._last_weights_at is not None
            and now - self._last_weights_at < self._config.weight_interval_seconds
        ):
            return None, "inside the weight submission interval"

        submission = self._registry.submission(neurons)
        if not submission:
            return None, "no scored miners to weight yet"

        try:
            result = self._submitter.set_weights(self._config.netuid, submission.weights)
        except ChainError as exc:
            logger.error("weight submission failed: %s", exc)
            return None, f"submission failed: {exc}"

        self._last_weights_at = now
        logger.info(
            "submitted weights for %d miners (%d provisional): %s",
            len(submission.weights),
            len(submission.provisional_uids),
            result,
        )
        return dict(submission.weights), result

    # --- the loop -------------------------------------------------------------------

    def run_once(self) -> RoundReport:
        """One full iteration. Never raises for an operational failure."""
        errors: list[str] = []

        try:
            neurons = self.sync()
        except ChainError as exc:
            logger.error("metagraph sync failed: %s", exc)
            return RoundReport(errors=(f"sync failed: {exc}",))

        # Resolution first: settling due tasks before issuing a new one keeps reputation
        # as current as possible for the weights submitted at the end of this round.
        try:
            resolutions = self.resolve_due()
        except Exception as exc:  # storage or provider failure
            logger.exception("resolution pass failed")
            resolutions = ()
            errors.append(f"resolution pass failed: {exc}")

        miners = self.miners(neurons)
        task = None
        rejected: dict[int, str] = {}
        collected = 0
        try:
            task, rejected = self.issue_task(miners)
            if task is not None:
                collected = len(miners) - len(rejected)
        except MarketDataError as exc:
            logger.warning("could not issue a task this round: %s", exc)
            errors.append(f"task issuance failed: {exc}")
        except Exception as exc:
            logger.exception("task issuance failed")
            errors.append(f"task issuance failed: {exc}")

        weights, weight_result = self.submit_weights(neurons)

        return RoundReport(
            task_id=None if task is None else task.task_id,
            queried=len(miners),
            collected=max(0, collected),
            rejected=rejected,
            resolutions=resolutions,
            weights_submitted=weights,
            weight_result=weight_result,
            errors=tuple(errors),
        )

    def run(
        self, *, max_rounds: int | None = None, sleep: Callable[[float], None] = time.sleep
    ) -> int:
        """Run the validator loop.

        Args:
            max_rounds: stop after this many iterations (used by the end-to-end proof).
                ``None`` runs until interrupted.

        Returns:
            The number of rounds completed.
        """
        completed = 0
        while max_rounds is None or completed < max_rounds:
            started = self._clock()
            report = self.run_once()
            completed += 1
            for error in report.errors:
                logger.error("round error: %s", error)
            if max_rounds is not None and completed >= max_rounds:
                break
            elapsed = self._clock() - started
            remaining = self._config.task_interval_seconds - elapsed
            if remaining > 0:
                sleep(remaining)
        return completed
