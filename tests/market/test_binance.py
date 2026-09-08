from __future__ import annotations

import pytest

from tests.market.helpers import RecordedTransport, json_response, load_fixture
from vanta.market.binance import BinanceVisionProvider
from vanta.market.errors import MalformedMarketDataError, ProviderError

# Fixture candles open at these seconds (recorded from the live mirror).
FIXTURE_START = 1_788_907_020
FIXTURE_END = FIXTURE_START + 3 * 60


def test_parses_the_recorded_live_response() -> None:
    transport = RecordedTransport([load_fixture("binance_klines_1m.json"), b"[]"])
    provider = BinanceVisionProvider(transport)

    candles = provider.fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_END)

    assert len(candles) == 3
    assert candles[0].open_time == FIXTURE_START
    assert candles[0].open == pytest.approx(2483.86)
    assert candles[0].high == pytest.approx(2484.84)
    assert candles[0].low == pytest.approx(2483.85)
    assert candles[0].close == pytest.approx(2484.61)
    assert candles[0].volume == pytest.approx(44.7517)
    assert [c.open_time for c in candles] == [
        FIXTURE_START,
        FIXTURE_START + 60,
        FIXTURE_START + 120,
    ]


def test_targets_the_vision_mirror_not_the_blocked_host() -> None:
    transport = RecordedTransport([load_fixture("binance_klines_1m.json"), b"[]"])
    BinanceVisionProvider(transport).fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_END)
    url = transport.urls[0]
    assert url.startswith("https://data-api.binance.vision/api/v3/klines")
    assert "api.binance.com" not in url
    assert "fapi.binance.com" not in url


def test_maps_the_canonical_asset_to_the_usdt_symbol() -> None:
    transport = RecordedTransport([load_fixture("binance_klines_1m.json"), b"[]"])
    BinanceVisionProvider(transport).fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_END)
    assert "symbol=ETHUSDT" in transport.urls[0]
    assert "interval=1m" in transport.urls[0]


def test_requests_a_half_open_millisecond_window() -> None:
    transport = RecordedTransport([b"[]"])
    BinanceVisionProvider(transport).fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_END)
    assert f"startTime={FIXTURE_START * 1000}" in transport.urls[0]
    assert f"endTime={FIXTURE_END * 1000 - 1}" in transport.urls[0]


def test_paginates_until_the_window_is_covered() -> None:
    first = [
        [(FIXTURE_START + i * 60) * 1000, "10.0", "10.0", "10.0", "10.0", "1.0"] for i in range(2)
    ]
    second = [[(FIXTURE_START + 120) * 1000, "10.0", "10.0", "10.0", "10.0", "1.0"]]
    transport = RecordedTransport([json_response(first), json_response(second), b"[]"])

    candles = BinanceVisionProvider(transport).fetch_candles(
        "ETH-USD", 60, FIXTURE_START, FIXTURE_END
    )

    assert len(candles) == 3
    assert len(transport.urls) >= 2


def test_empty_window_makes_no_request() -> None:
    transport = RecordedTransport([])
    assert BinanceVisionProvider(transport).fetch_candles("ETH-USD", 60, 100, 100) == []
    assert transport.urls == []


def test_unknown_asset_is_rejected() -> None:
    with pytest.raises(ProviderError, match="no symbol mapping"):
        BinanceVisionProvider(RecordedTransport([])).fetch_candles("BTC-USD", 60, 0, 60)


def test_unsupported_interval_is_rejected() -> None:
    with pytest.raises(ProviderError, match="does not serve a 45s interval"):
        BinanceVisionProvider(RecordedTransport([])).fetch_candles("ETH-USD", 45, 0, 45)


def test_unparseable_body_is_a_provider_error() -> None:
    transport = RecordedTransport([b"<html>451</html>"])
    with pytest.raises(ProviderError, match="unparseable JSON"):
        BinanceVisionProvider(transport).fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_END)


def test_non_list_body_is_a_provider_error() -> None:
    transport = RecordedTransport([json_response({"code": -1121, "msg": "Invalid symbol."})])
    with pytest.raises(ProviderError, match="expected a list"):
        BinanceVisionProvider(transport).fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_END)


def test_short_row_is_malformed() -> None:
    transport = RecordedTransport([json_response([[FIXTURE_START * 1000, "10.0"]])])
    with pytest.raises(MalformedMarketDataError, match="malformed"):
        BinanceVisionProvider(transport).fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_END)


def test_non_numeric_row_is_malformed() -> None:
    row = [[FIXTURE_START * 1000, "n/a", "10.0", "10.0", "10.0", "1.0"]]
    transport = RecordedTransport([json_response(row)])
    with pytest.raises(MalformedMarketDataError, match="non-numeric"):
        BinanceVisionProvider(transport).fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_END)


def test_runaway_pagination_is_capped() -> None:
    row = [[FIXTURE_START * 1000, "10.0", "10.0", "10.0", "10.0", "1.0"]]
    transport = RecordedTransport([json_response(row)] * 10)
    provider = BinanceVisionProvider(transport, max_requests=3)
    with pytest.raises(ProviderError, match="exceeded 3 requests"):
        provider.fetch_candles("ETH-USD", 60, FIXTURE_START, FIXTURE_START + 100 * 60)
