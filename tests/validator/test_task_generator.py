"""Task generation (§7) and its structural no-look-ahead guarantee (§27, §29)."""

from __future__ import annotations

import pytest

from vanta.market.errors import MarketDataError
from vanta.market.resolution import ResolutionEngine
from vanta.validation import VantaValidationError
from vanta.validator.task_generator import TaskGenerator, task_identifier

from ..neurons.helpers import INTERVAL, SeriesProvider, candles_from, drifting_closes

T = 1_788_900_000


def engine(*, closes: int = 200, end: int = T) -> ResolutionEngine:
    start = end - closes * INTERVAL
    provider = SeriesProvider(candles_from(drifting_closes(closes), start=start))
    return ResolutionEngine(provider, candle_interval_seconds=INTERVAL)


def generator(**overrides: object) -> TaskGenerator:
    values: dict[str, object] = {
        "resolution": engine(),
        "asset": "ETH-USD",
        "horizon_seconds": 900,
        "submission_window_seconds": 30,
        "clock": lambda: float(T),
    }
    values.update(overrides)
    return TaskGenerator(**values)  # type: ignore[arg-type]


class TestGeneration:
    def test_builds_a_task_at_the_current_instant(self) -> None:
        task = generator().generate()
        assert task.timestamp == T
        assert task.asset == "ETH-USD"
        assert task.horizon_seconds == 900
        assert task.reference_price > 0.0

    def test_the_deadline_falls_before_resolution(self) -> None:
        """§27/§29: the submission window must close before the outcome is knowable."""
        task = generator().generate()
        assert task.deadline == T + 30
        assert task.deadline < task.resolve_at
        assert task.resolve_at == T + 900

    def test_prices_the_task_from_the_market_feed(self) -> None:
        closes = drifting_closes(200)
        provider = SeriesProvider(candles_from(closes, start=T - 200 * INTERVAL))
        task = generator(
            resolution=ResolutionEngine(provider, candle_interval_seconds=INTERVAL)
        ).generate()
        assert task.reference_price == pytest.approx(closes[-1])

    def test_an_explicit_timestamp_overrides_the_clock(self) -> None:
        task = generator().generate(T - 600)
        assert task.timestamp == T - 600

    def test_propagates_a_market_data_failure(self) -> None:
        empty = ResolutionEngine(SeriesProvider([]), candle_interval_seconds=INTERVAL)
        with pytest.raises(MarketDataError):
            generator(resolution=empty).generate()


class TestIdentifier:
    def test_is_deterministic(self) -> None:
        """§24: honest validators must agree on the task universe."""
        assert task_identifier("ETH-USD", 900, T) == task_identifier("ETH-USD", 900, T)

    def test_distinguishes_asset_horizon_and_instant(self) -> None:
        base = task_identifier("ETH-USD", 900, T)
        assert base != task_identifier("BTC-USD", 900, T)
        assert base != task_identifier("ETH-USD", 3600, T)
        assert base != task_identifier("ETH-USD", 900, T + 1)

    def test_two_validators_generate_the_same_id_for_the_same_instant(self) -> None:
        first = generator().generate()
        second = generator().generate()
        assert first.task_id == second.task_id


class TestConfiguration:
    def test_rejects_a_window_reaching_the_resolution_time(self) -> None:
        with pytest.raises(VantaValidationError, match="observe the outcome"):
            generator(submission_window_seconds=900)

    def test_rejects_a_window_beyond_the_horizon(self) -> None:
        with pytest.raises(VantaValidationError, match="observe the outcome"):
            generator(submission_window_seconds=1800)

    @pytest.mark.parametrize("window", [0, -1])
    def test_rejects_a_non_positive_window(self, window: int) -> None:
        with pytest.raises(VantaValidationError, match="submission_window_seconds"):
            generator(submission_window_seconds=window)

    @pytest.mark.parametrize("horizon", [0, -900])
    def test_rejects_a_non_positive_horizon(self, horizon: int) -> None:
        with pytest.raises(VantaValidationError, match="horizon_seconds"):
            generator(horizon_seconds=horizon)
