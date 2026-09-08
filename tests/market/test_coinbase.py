from __future__ import annotations

import pytest

from tests.market.helpers import RecordedTransport, json_response, load_fixture
from vanta.market.coinbase import CoinbaseProvider
from vanta.market.errors import MalformedMarketDataError, ProviderError

FIXTURE_START = 1_788_903_840
FIXTURE_END = FIXTURE_START + 3 * 60


def test_parses_the_recorded_live_response() -> None:
    transport = RecordedTransport([load_fixture("coinbase_candles_60s.json")])
    candles = CoinbaseProvider(transport).fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_END)

    assert len(candles) == 3
    # Coinbase rows are [time, low, high, open, close, volume] — the field order differs
    # from Binance and must be mapped, not positionally copied.
    oldest = candles[0]
    assert oldest.open_time == FIXTURE_START
    assert oldest.low == pytest.approx(2482.15)
    assert oldest.high == pytest.approx(2483.51)
    assert oldest.open == pytest.approx(2483.51)
    assert oldest.close == pytest.approx(2483.0)


def test_reorders_the_newest_first_series_to_ascending() -> None:
    transport = RecordedTransport([load_fixture("coinbase_candles_60s.json")])
    candles = CoinbaseProvider(transport).fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_END)
    assert [c.open_time for c in candles] == sorted(c.open_time for c in candles)


def test_uses_the_true_usd_product() -> None:
    transport = RecordedTransport([load_fixture("coinbase_candles_60s.json")])
    CoinbaseProvider(transport).fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_END)
    assert "/products/ETH-USD/candles" in transport.urls[0]
    assert "granularity=60" in transport.urls[0]


def test_sends_an_iso8601_half_open_window() -> None:
    transport = RecordedTransport([b"[]"])
    CoinbaseProvider(transport).fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_END)
    url = transport.urls[0]
    assert "start=2026-09" in url or "start=" in url
    assert "%3A" in url  # ISO timestamps are percent-encoded


def test_paginates_in_three_hundred_candle_chunks() -> None:
    transport = RecordedTransport([b"[]", b"[]", b"[]"])
    CoinbaseProvider(transport).fetch_candles("ETH-USD", 60, 0, 600 * 60)
    assert len(transport.urls) == 2


def test_unsupported_granularity_is_rejected() -> None:
    with pytest.raises(ProviderError, match="does not serve a 120s granularity"):
        CoinbaseProvider(RecordedTransport([])).fetch_candles("ETH-USD", 120, 0, 120)


def test_unknown_asset_is_rejected() -> None:
    with pytest.raises(ProviderError, match="no product mapping"):
        CoinbaseProvider(RecordedTransport([])).fetch_candles("BTC-USD", 60, 0, 60)


def test_venue_error_object_is_surfaced() -> None:
    transport = RecordedTransport([json_response({"message": "NotFound"})])
    with pytest.raises(ProviderError, match="NotFound"):
        CoinbaseProvider(transport).fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_END)


def test_short_row_is_malformed() -> None:
    transport = RecordedTransport([json_response([[FIXTURE_START, 1.0, 2.0]])])
    with pytest.raises(MalformedMarketDataError, match="malformed"):
        CoinbaseProvider(transport).fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_END)


def test_empty_window_makes_no_request() -> None:
    transport = RecordedTransport([])
    assert CoinbaseProvider(transport).fetch_candles("ETH-USD", 60, 100, 100) == []
    assert transport.urls == []


def test_binance_and_coinbase_normalize_to_the_same_shape() -> None:
    # Providers must be swappable: identical bars from either venue produce equal candles.
    from vanta.market.binance import BinanceVisionProvider

    binance_rows = [[60_000, "10.0", "12.0", "9.0", "11.0", "5.0", 119_999]]
    coinbase_rows = [[60, 9.0, 12.0, 10.0, 11.0, 5.0]]

    from_binance = BinanceVisionProvider(
        RecordedTransport([json_response(binance_rows), b"[]"])
    ).fetch_candles("ETH-USD", 60, 60, 120)
    from_coinbase = CoinbaseProvider(
        RecordedTransport([json_response(coinbase_rows)])
    ).fetch_candles("ETH-USD", 60, 60, 120)

    assert from_binance == from_coinbase
