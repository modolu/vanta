"""Historical replay of the full Vanta loop (ARCHITECTURE.md §41).

Runs market data -> task -> forecasts -> resolution -> scoring -> reputation -> weights
-> consensus over a recorded ETH history, so the mechanism can be shown to behave as
intended without waiting weeks for live outcomes.

Three properties this file exists to guarantee:

* **Chronological.** Tasks are replayed in time order and state only ever moves forward.
* **Causal.** Everything an engine sees, and the §17 return scale itself, is derived from
  the bounded window at ``T``. The resolution price is fetched only after every forecast
  for that task has been collected.
* **Deterministic.** No clock, no RNG beyond the seeded random engine, no dependence on
  iteration order. The same candles and config always produce the same leaderboard.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from vanta.consensus.aggregator import consensus_probability
from vanta.forecasting.base import ForecastContext, ForecastEngine
from vanta.log import get_logger
from vanta.market.errors import MarketDataError
from vanta.market.resolution import return_scale_from_closes
from vanta.protocol.forecast import Direction, Forecast, ForecastTask, Resolution
from vanta.simulation.series import CandleSeries
from vanta.validator.reputation import DEFAULT_EMA_ALPHA, MinerReputation
from vanta.validator.scorer import ForecastScore, score_forecast
from vanta.validator.weights import DEFAULT_GAMMA, compute_weights

__all__ = [
    "Checkpoint",
    "DatasetInfo",
    "LeaderboardRow",
    "MinerStats",
    "SimulationConfig",
    "SimulationResult",
    "run_simulation",
]

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    """Provenance of the replayed history, recorded so a run can be reproduced."""

    source: str
    symbol: str
    interval_seconds: int
    start_time: int
    end_time: int
    candle_count: int


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    asset: str = "ETH-USD"
    horizon_seconds: int = 900
    # Non-overlapping by default: back-to-back horizons keep outcomes independent, where
    # overlapping tasks would inflate the count with correlated observations.
    spacing_seconds: int | None = None
    lookback_candles: int = 600
    max_staleness_seconds: int = 120
    volatility_min_samples: int = 20
    submission_window_seconds: int = 30
    ema_alpha: float = DEFAULT_EMA_ALPHA
    gamma: float = DEFAULT_GAMMA
    checkpoints: tuple[int, ...] = (10, 100, 500, 1000)
    max_tasks: int | None = None

    @property
    def task_spacing(self) -> int:
        return self.spacing_seconds or self.horizon_seconds


@dataclass(slots=True)
class MinerStats:
    """Running accumulators for one miner across the replay."""

    uid: int
    name: str
    reputation: MinerReputation
    total_score_sum: float = 0.0
    brier_sum: float = 0.0
    probability_quality_sum: float = 0.0
    return_score_sum: float = 0.0
    absolute_return_error_sum: float = 0.0
    direction_hits: int = 0
    forecast_count: int = 0

    def record(self, score: ForecastScore, forecast: Forecast, resolution: Resolution) -> None:
        self.total_score_sum += score.total_score
        self.brier_sum += score.brier
        self.probability_quality_sum += score.probability_quality
        self.return_score_sum += score.return_score
        self.absolute_return_error_sum += abs(forecast.expected_return - resolution.realized_return)
        called_up = forecast.probability_up > 0.5
        if called_up == (resolution.direction is Direction.UP):
            self.direction_hits += 1
        self.forecast_count += 1
        # Reputation is folded in last, so the calibration term used to score this
        # forecast came from the miner's state *before* it.
        self.reputation.record(
            score.total_score, forecast.probability_up, resolution.require_outcome()
        )

    def _mean(self, total: float) -> float:
        return total / self.forecast_count if self.forecast_count else 0.0

    @property
    def mean_score(self) -> float:
        return self._mean(self.total_score_sum)

    @property
    def mean_brier(self) -> float:
        return self._mean(self.brier_sum)

    @property
    def mean_probability_quality(self) -> float:
        return self._mean(self.probability_quality_sum)

    @property
    def mean_return_score(self) -> float:
        return self._mean(self.return_score_sum)

    @property
    def mean_absolute_return_error(self) -> float:
        return self._mean(self.absolute_return_error_sum)

    @property
    def directional_accuracy(self) -> float:
        return self.direction_hits / self.forecast_count if self.forecast_count else 0.0


@dataclass(frozen=True, slots=True)
class LeaderboardRow:
    rank: int
    uid: int
    name: str
    mean_score: float
    ema_reputation: float
    probability_quality: float
    brier: float
    return_score: float
    calibration: float
    weight: float
    directional_accuracy: float
    mean_absolute_return_error: float
    forecast_count: int
    provisional: bool


@dataclass(frozen=True, slots=True)
class Checkpoint:
    valid_tasks: int
    rows: tuple[LeaderboardRow, ...]


@dataclass(slots=True)
class ConsensusStats:
    """How the network's aggregate forecast performed, as its own participant."""

    count: int = 0
    hits: int = 0
    probability_sum: float = 0.0
    dispersion_sum: float = 0.0
    brier_sum: float = 0.0

    @property
    def directional_accuracy(self) -> float:
        return self.hits / self.count if self.count else 0.0

    @property
    def mean_probability(self) -> float:
        return self.probability_sum / self.count if self.count else 0.0

    @property
    def mean_dispersion(self) -> float:
        return self.dispersion_sum / self.count if self.count else 0.0

    @property
    def mean_brier(self) -> float:
        return self.brier_sum / self.count if self.count else 0.0


@dataclass(frozen=True, slots=True)
class SimulationResult:
    dataset: DatasetInfo
    config: SimulationConfig
    checkpoints: tuple[Checkpoint, ...]
    final: Checkpoint
    valid_tasks: int
    void_tasks: int
    unresolvable_tasks: int
    incomplete_tasks: int
    attempted_tasks: int
    consensus: ConsensusStats
    engine_names: tuple[str, ...] = field(default=())


def _snapshot(miners: dict[int, MinerStats], valid_tasks: int, *, gamma: float) -> Checkpoint:
    weights = compute_weights(
        {uid: stats.reputation.score for uid, stats in miners.items()}, gamma=gamma
    )
    rows = [
        LeaderboardRow(
            rank=0,
            uid=uid,
            name=stats.name,
            mean_score=stats.mean_score,
            ema_reputation=stats.reputation.score,
            probability_quality=stats.mean_probability_quality,
            brier=stats.mean_brier,
            return_score=stats.mean_return_score,
            calibration=stats.reputation.calibration_component,
            weight=weights[uid],
            directional_accuracy=stats.directional_accuracy,
            mean_absolute_return_error=stats.mean_absolute_return_error,
            forecast_count=stats.forecast_count,
            provisional=stats.reputation.is_provisional,
        )
        for uid, stats in miners.items()
    ]
    # Rank by the reputation that actually drives weights, breaking ties by uid so the
    # ordering is deterministic.
    rows.sort(key=lambda row: (-row.ema_reputation, row.uid))
    ranked = tuple(replace(row, rank=index + 1) for index, row in enumerate(rows))
    return Checkpoint(valid_tasks=valid_tasks, rows=ranked)


def run_simulation(
    series: CandleSeries,
    engines: Sequence[ForecastEngine],
    config: SimulationConfig,
    dataset: DatasetInfo,
) -> SimulationResult:
    """Replay ``series`` through the full mechanism and return the evidence."""
    if not engines:
        raise ValueError("a simulation needs at least one engine")

    miners: dict[int, MinerStats] = {
        uid: MinerStats(
            uid=uid,
            name=engine.name,
            reputation=MinerReputation(miner_uid=uid, alpha=config.ema_alpha),
        )
        for uid, engine in enumerate(engines)
    }
    horizon_steps = config.horizon_seconds // series.interval_seconds

    checkpoints: list[Checkpoint] = []
    pending = sorted(set(config.checkpoints))
    consensus_stats = ConsensusStats()
    valid = void = unresolvable = incomplete = attempted = 0

    for task_time in series.task_times(
        spacing_seconds=config.task_spacing,
        warmup_candles=config.lookback_candles,
        horizon_seconds=config.horizon_seconds,
    ):
        if config.max_tasks is not None and valid >= config.max_tasks:
            break
        attempted += 1

        try:
            reference_price = series.price_at(
                task_time, max_staleness_seconds=config.max_staleness_seconds
            )
            window = series.window_at(task_time, config.lookback_candles)
            return_scale = return_scale_from_closes(
                window.closes(), horizon_steps, min_samples=config.volatility_min_samples
            )
        except MarketDataError:
            unresolvable += 1
            continue

        task = ForecastTask(
            task_id=f"{config.asset}-{config.horizon_seconds}s-{task_time}",
            asset=config.asset,
            reference_price=reference_price,
            timestamp=task_time,
            horizon_seconds=config.horizon_seconds,
            deadline=task_time + config.submission_window_seconds,
        )
        context = ForecastContext(task=task, history=window)

        # Every engine must answer, or the task is dropped for everyone. That keeps the
        # task universe identical across miners, which is what makes their scores
        # comparable and lets independent validators agree (§24).
        forecasts: dict[int, Forecast] = {}
        for uid, engine in enumerate(engines):
            try:
                forecasts[uid] = engine.forecast(context, miner_uid=uid)
            except MarketDataError:
                break
        if len(forecasts) != len(engines):
            incomplete += 1
            continue

        try:
            resolution_price = series.price_at(
                task.resolve_at, max_staleness_seconds=config.max_staleness_seconds
            )
        except MarketDataError:
            unresolvable += 1
            continue

        resolution = Resolution.from_task(task, resolution_price=resolution_price)
        if resolution.is_void:
            # Exactly flat: no directional outcome, so no miner state is touched (§14).
            void += 1
            continue

        # Consensus is a forecast-time product, so it uses reputation as it stood before
        # this task resolved.
        consensus = consensus_probability(
            {uid: forecast.probability_up for uid, forecast in forecasts.items()},
            {uid: stats.reputation.score for uid, stats in miners.items()},
        )
        outcome = resolution.require_outcome()
        consensus_stats.count += 1
        consensus_stats.probability_sum += consensus.probability_up
        consensus_stats.dispersion_sum += consensus.dispersion
        consensus_stats.brier_sum += (consensus.probability_up - outcome) ** 2
        if (consensus.probability_up > 0.5) == (resolution.direction is Direction.UP):
            consensus_stats.hits += 1

        for uid, forecast in forecasts.items():
            stats = miners[uid]
            score = score_forecast(
                forecast,
                resolution,
                return_scale=return_scale,
                calibration_component=stats.reputation.calibration_component,
            )
            stats.record(score, forecast, resolution)

        valid += 1
        while pending and valid >= pending[0]:
            checkpoints.append(_snapshot(miners, valid, gamma=config.gamma))
            pending.pop(0)

    final = _snapshot(miners, valid, gamma=config.gamma)
    logger.info(
        "replay complete: %d valid, %d void, %d unresolvable, %d incomplete of %d attempted",
        valid,
        void,
        unresolvable,
        incomplete,
        attempted,
    )
    return SimulationResult(
        dataset=dataset,
        config=config,
        checkpoints=tuple(checkpoints),
        final=final,
        valid_tasks=valid,
        void_tasks=void,
        unresolvable_tasks=unresolvable,
        incomplete_tasks=incomplete,
        attempted_tasks=attempted,
        consensus=consensus_stats,
        engine_names=tuple(engine.name for engine in engines),
    )
