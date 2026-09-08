from __future__ import annotations

import math

import pytest

from tests.forecasting.helpers import (
    T,
    choppy,
    context_ending_at,
    flat,
    spike,
    trend,
)
from vanta.forecasting import (
    AdversarialEngine,
    MeanReversionEngine,
    MomentumEngine,
    PersistenceEngine,
    RandomEngine,
    default_engines,
)
from vanta.market.errors import InsufficientMarketDataError
from vanta.protocol.forecast import Direction
from vanta.validation import VantaValidationError

RISING = trend(300, step=0.0008)
FALLING = trend(300, step=-0.0008)


@pytest.mark.parametrize("engine", default_engines(), ids=lambda e: e.name)
class TestEveryEngine:
    @pytest.mark.parametrize("closes", [RISING, FALLING, choppy(300), spike(300)])
    def test_produces_a_valid_forecast(self, engine, closes: list[float]) -> None:
        forecast = engine.forecast(context_ending_at(closes), miner_uid=3)
        assert 0.0 <= forecast.probability_up <= 1.0
        assert math.isfinite(forecast.expected_return)
        assert forecast.task_id == context_ending_at(closes).task.task_id

    def test_is_deterministic_for_identical_input(self, engine) -> None:
        first = engine.forecast(context_ending_at(RISING), miner_uid=3)
        second = engine.forecast(context_ending_at(RISING), miner_uid=3)
        assert first == second

    def test_records_its_model_version(self, engine) -> None:
        forecast = engine.forecast(context_ending_at(RISING), miner_uid=3)
        assert forecast.model_version == f"{engine.name}-v1"

    def test_short_history_fails_explicitly(self, engine) -> None:
        if engine.min_history == 0 and engine.name != "ml":
            pytest.skip(f"{engine.name} needs no history by design")
        with pytest.raises(InsufficientMarketDataError):
            engine.forecast(context_ending_at(flat(5)), miner_uid=3)


class TestRandomEngine:
    def test_is_reproducible_under_a_seed(self) -> None:
        context = context_ending_at(RISING)
        assert RandomEngine(seed=42).predict(context) == RandomEngine(seed=42).predict(context)

    def test_different_seeds_diverge(self) -> None:
        context = context_ending_at(RISING)
        assert RandomEngine(seed=1).predict(context) != RandomEngine(seed=2).predict(context)

    def test_different_tasks_get_different_draws(self) -> None:
        engine = RandomEngine(seed=7)
        first = engine.predict(context_ending_at(RISING, timestamp=T))
        second = engine.predict(context_ending_at(RISING, timestamp=T + 900))
        assert first != second

    def test_seeding_does_not_depend_on_process_hash_randomization(self) -> None:
        # A salted hash() would make the same task irreproducible across machines.
        from vanta.forecasting.random import _deterministic_seed

        assert _deterministic_seed(5, "eth-900s-1") == _deterministic_seed(5, "eth-900s-1")
        assert _deterministic_seed(5, "eth-900s-1") != _deterministic_seed(5, "eth-900s-2")

    def test_ignores_the_market_entirely(self) -> None:
        engine = RandomEngine(seed=3)
        rising = engine.predict(context_ending_at(RISING))
        falling = engine.predict(context_ending_at(FALLING))
        assert rising == falling

    def test_draws_spread_across_the_unit_interval(self) -> None:
        engine = RandomEngine(seed=11)
        draws = [
            engine.predict(context_ending_at(RISING, timestamp=T + i * 900)).probability_up
            for i in range(40)
        ]
        assert min(draws) < 0.25
        assert max(draws) > 0.75


class TestPersistenceEngine:
    def test_follows_a_rising_market(self) -> None:
        prediction = PersistenceEngine().predict(context_ending_at(RISING))
        assert prediction.probability_up > 0.5
        assert prediction.expected_return > 0.0

    def test_follows_a_falling_market(self) -> None:
        prediction = PersistenceEngine().predict(context_ending_at(FALLING))
        assert prediction.probability_up < 0.5
        assert prediction.expected_return < 0.0

    def test_is_neutral_on_a_flat_market(self) -> None:
        prediction = PersistenceEngine().predict(context_ending_at(flat(300)))
        assert prediction.probability_up == pytest.approx(0.5)
        assert prediction.expected_return == pytest.approx(0.0)

    def test_a_stronger_trend_gives_more_confidence(self) -> None:
        engine = PersistenceEngine()
        mild = engine.predict(context_ending_at(spike(300, size=0.002)))
        strong = engine.predict(context_ending_at(spike(300, size=0.02)))
        assert strong.probability_up > mild.probability_up

    def test_never_claims_certainty(self) -> None:
        # §16 punishes confident misses hardest, so an honest engine always hedges.
        prediction = PersistenceEngine().predict(context_ending_at(spike(300, size=0.5)))
        assert prediction.probability_up <= 0.99


class TestMeanReversionEngine:
    def test_fades_a_sharp_rally(self) -> None:
        prediction = MeanReversionEngine().predict(context_ending_at(spike(300, size=0.05)))
        assert prediction.probability_up < 0.5
        assert prediction.expected_return < 0.0

    def test_fades_a_sharp_selloff(self) -> None:
        prediction = MeanReversionEngine().predict(context_ending_at(spike(300, size=-0.05)))
        assert prediction.probability_up > 0.5
        assert prediction.expected_return > 0.0

    def test_reacts_oppositely_to_persistence(self) -> None:
        context = context_ending_at(spike(300, size=0.05))
        reversion = MeanReversionEngine().predict(context)
        persistence = PersistenceEngine().predict(context)
        assert (reversion.probability_up - 0.5) * (persistence.probability_up - 0.5) < 0

    def test_a_more_extreme_move_implies_stronger_reversal(self) -> None:
        engine = MeanReversionEngine()
        small = engine.predict(context_ending_at(spike(300, size=0.005)))
        large = engine.predict(context_ending_at(spike(300, size=0.05)))
        assert large.probability_up < small.probability_up


class TestMomentumEngine:
    def test_is_bullish_on_a_synthetic_uptrend(self) -> None:
        prediction = MomentumEngine().predict(context_ending_at(RISING))
        assert prediction.probability_up > 0.5
        assert prediction.expected_return > 0.0

    def test_is_bearish_on_a_synthetic_downtrend(self) -> None:
        prediction = MomentumEngine().predict(context_ending_at(FALLING))
        assert prediction.probability_up < 0.5
        assert prediction.expected_return < 0.0

    def test_expected_return_scales_with_volatility(self) -> None:
        engine = MomentumEngine()
        calm = engine.predict(context_ending_at(trend(300, step=0.0004)))
        wild = engine.predict(context_ending_at(trend(300, step=0.006)))
        assert abs(wild.expected_return) > abs(calm.expected_return)

    def test_stays_finite_on_a_flat_market(self) -> None:
        prediction = MomentumEngine().predict(context_ending_at(flat(300)))
        assert math.isfinite(prediction.expected_return)
        assert 0.0 <= prediction.probability_up <= 1.0


class TestAdversarialEngine:
    def test_is_extremely_confident(self) -> None:
        prediction = AdversarialEngine().predict(context_ending_at(RISING))
        assert prediction.probability_up == pytest.approx(0.99)

    def test_holds_that_confidence_against_the_market(self) -> None:
        # §25 attack 2 + 3: always up, always certain, regardless of evidence.
        engine = AdversarialEngine()
        assert engine.predict(context_ending_at(RISING)) == engine.predict(
            context_ending_at(FALLING)
        )

    def test_can_be_pointed_downward(self) -> None:
        prediction = AdversarialEngine(direction=Direction.DOWN).predict(context_ending_at(RISING))
        assert prediction.probability_up == pytest.approx(0.01)
        assert prediction.expected_return < 0.0

    def test_confidence_must_actually_be_confident(self) -> None:
        with pytest.raises(VantaValidationError, match=r"confidence > 0\.5"):
            AdversarialEngine(confidence=0.4)

    def test_needs_no_history(self) -> None:
        forecast = AdversarialEngine().forecast(context_ending_at(flat(2)), miner_uid=1)
        assert forecast.probability_up == pytest.approx(0.99)
