from __future__ import annotations

import math

import pytest

from tests.market.helpers import make_candle
from vanta.market.errors import (
    AllProvidersFailedError,
    MalformedMarketDataError,
    MarketDataError,
    ProviderError,
)
from vanta.market.provider import Candle, FailoverProvider, MarketDataProvider


class TestCandle:
    def test_close_time_is_open_time_plus_interval(self) -> None:
        assert make_candle(60, 100.0, interval=900).close_time == 960

    def test_accepts_a_well_formed_bar(self) -> None:
        candle = Candle(
            open_time=60,
            open=100.0,
            high=105.0,
            low=99.0,
            close=103.0,
            volume=1.5,
            interval_seconds=60,
        )
        assert candle.close == 103.0

    @pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
    def test_non_positive_or_non_finite_prices_are_rejected(self, bad: float) -> None:
        with pytest.raises(MalformedMarketDataError):
            Candle(
                open_time=60,
                open=bad,
                high=105.0,
                low=99.0,
                close=103.0,
                volume=1.0,
                interval_seconds=60,
            )

    def test_negative_volume_is_rejected(self) -> None:
        with pytest.raises(MalformedMarketDataError, match="volume"):
            Candle(
                open_time=60,
                open=100.0,
                high=105.0,
                low=99.0,
                close=103.0,
                volume=-1.0,
                interval_seconds=60,
            )

    def test_high_below_the_body_is_rejected(self) -> None:
        with pytest.raises(MalformedMarketDataError, match="high"):
            Candle(
                open_time=60,
                open=100.0,
                high=99.0,
                low=98.0,
                close=100.0,
                volume=1.0,
                interval_seconds=60,
            )

    def test_low_above_the_body_is_rejected(self) -> None:
        with pytest.raises(MalformedMarketDataError, match="low"):
            Candle(
                open_time=60,
                open=100.0,
                high=105.0,
                low=101.0,
                close=100.0,
                volume=1.0,
                interval_seconds=60,
            )

    def test_non_positive_interval_is_rejected(self) -> None:
        with pytest.raises(MalformedMarketDataError, match="interval_seconds"):
            make_candle(60, 100.0, interval=0)

    def test_is_immutable(self) -> None:
        with pytest.raises((AttributeError, TypeError)):
            make_candle(60, 100.0).close = 1.0  # type: ignore[misc]


class _StubProvider(MarketDataProvider):
    def __init__(self, name: str, result: list[Candle] | Exception) -> None:
        self.name = name  # type: ignore[misc]
        self._result = result
        self.calls = 0

    def fetch_candles(
        self, asset: str, interval_seconds: int, start_time: int, end_time: int
    ) -> list[Candle]:
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class TestFailoverProvider:
    def test_uses_the_primary_when_it_succeeds(self) -> None:
        primary = _StubProvider("primary", [make_candle(60, 100.0)])
        fallback = _StubProvider("fallback", [make_candle(60, 200.0)])
        result = FailoverProvider([primary, fallback]).fetch_candles("ETH-USD", 60, 60, 120)
        assert result[0].close == 100.0
        assert fallback.calls == 0

    def test_falls_back_when_the_primary_fails(self) -> None:
        primary = _StubProvider("primary", ProviderError("451 blocked"))
        fallback = _StubProvider("fallback", [make_candle(60, 200.0)])
        result = FailoverProvider([primary, fallback]).fetch_candles("ETH-USD", 60, 60, 120)
        assert result[0].close == 200.0
        assert primary.calls == 1
        assert fallback.calls == 1

    def test_raises_when_every_provider_fails(self) -> None:
        chain = FailoverProvider(
            [
                _StubProvider("primary", ProviderError("451 blocked")),
                _StubProvider("fallback", MarketDataError("timeout")),
            ]
        )
        with pytest.raises(AllProvidersFailedError) as excinfo:
            chain.fetch_candles("ETH-USD", 60, 60, 120)
        # The message must name every venue so an operator can see what actually broke.
        assert "primary: 451 blocked" in str(excinfo.value)
        assert "fallback: timeout" in str(excinfo.value)

    def test_programming_errors_are_not_swallowed_by_failover(self) -> None:
        primary = _StubProvider("primary", TypeError("bug in the parser"))
        fallback = _StubProvider("fallback", [make_candle(60, 200.0)])
        with pytest.raises(TypeError, match="bug in the parser"):
            FailoverProvider([primary, fallback]).fetch_candles("ETH-USD", 60, 60, 120)
        assert fallback.calls == 0

    def test_requires_at_least_one_provider(self) -> None:
        with pytest.raises(ValueError, match="at least one provider"):
            FailoverProvider([])

    def test_exposes_its_chain_in_order(self) -> None:
        primary = _StubProvider("primary", [])
        fallback = _StubProvider("fallback", [])
        assert FailoverProvider([primary, fallback]).providers == (primary, fallback)
