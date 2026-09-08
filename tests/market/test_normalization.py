from __future__ import annotations

import pytest

from tests.market.helpers import make_candle, make_series
from vanta.market.errors import MalformedMarketDataError
from vanta.market.normalization import align_down, normalize_asset, normalize_candles


class TestNormalizeAsset:
    @pytest.mark.parametrize("raw", ["ETH-USD", "eth-usd", "  ETH-usd  "])
    def test_canonicalizes_case_and_whitespace(self, raw: str) -> None:
        assert normalize_asset(raw) == "ETH-USD"

    @pytest.mark.parametrize("bad", ["ETHUSD", "ETH-", "-USD", "", "ETH-USD-PERP", 42])
    def test_rejects_malformed_assets(self, bad: object) -> None:
        with pytest.raises(MalformedMarketDataError):
            normalize_asset(bad)  # type: ignore[arg-type]


class TestAlignDown:
    def test_rounds_to_the_candle_start(self) -> None:
        assert align_down(1_000_000_037, 60) == 1_000_000_020
        assert align_down(1_000_000_020, 60) == 1_000_000_020

    def test_rejects_a_non_positive_interval(self) -> None:
        with pytest.raises(MalformedMarketDataError):
            align_down(100, 0)


class TestNormalizeCandles:
    def test_sorts_a_descending_series(self) -> None:
        # Coinbase returns newest-first.
        descending = list(reversed(make_series(60, [100.0, 101.0, 102.0])))
        result = normalize_candles(descending, interval_seconds=60)
        assert [c.open_time for c in result] == [60, 120, 180]

    def test_drops_identical_duplicates(self) -> None:
        candle = make_candle(60, 100.0)
        result = normalize_candles([candle, candle], interval_seconds=60)
        assert len(result) == 1

    def test_conflicting_duplicates_are_an_error(self) -> None:
        with pytest.raises(MalformedMarketDataError, match="conflicting"):
            normalize_candles([make_candle(60, 100.0), make_candle(60, 105.0)], interval_seconds=60)

    def test_rejects_a_mismatched_interval(self) -> None:
        with pytest.raises(MalformedMarketDataError, match="expected 60s"):
            normalize_candles([make_candle(900, 100.0, interval=900)], interval_seconds=60)

    def test_rejects_misaligned_open_times(self) -> None:
        with pytest.raises(MalformedMarketDataError, match="not aligned"):
            normalize_candles([make_candle(37, 100.0)], interval_seconds=60)

    def test_rejects_a_gap_by_default(self) -> None:
        with pytest.raises(MalformedMarketDataError, match="gap in candle series"):
            normalize_candles(
                [make_candle(60, 100.0), make_candle(180, 102.0)], interval_seconds=60
            )

    def test_gaps_can_be_tolerated_explicitly(self) -> None:
        result = normalize_candles(
            [make_candle(60, 100.0), make_candle(180, 102.0)],
            interval_seconds=60,
            require_contiguous=False,
        )
        assert len(result) == 2

    def test_applies_the_half_open_window(self) -> None:
        result = normalize_candles(
            make_series(60, [100.0, 101.0, 102.0, 103.0]),
            interval_seconds=60,
            start_time=120,
            end_time=240,
        )
        assert [c.open_time for c in result] == [120, 180]

    def test_empty_input_is_allowed(self) -> None:
        assert normalize_candles([], interval_seconds=60) == []
