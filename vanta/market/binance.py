"""Binance Vision market-data provider — the primary source (§13).

``data-api.binance.vision`` is Binance's unauthenticated market-data mirror. It is used
instead of ``api.binance.com``/``fapi.binance.com``, which return HTTP 451 from our
deployment location.

Note: Binance quotes ETH against USDT, not USD. See ``asset`` handling below.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, ClassVar
from urllib.parse import urlencode

from vanta.market.errors import MalformedMarketDataError, ProviderError
from vanta.market.normalization import normalize_asset, normalize_candles
from vanta.market.provider import (
    DEFAULT_TIMEOUT_SECONDS,
    Candle,
    HttpTransport,
    MarketDataProvider,
    urllib_get,
)

__all__ = ["BinanceVisionProvider"]

# Binance's kline interval strings, keyed by seconds.
_INTERVALS: Mapping[int, str] = {
    60: "1m",
    180: "3m",
    300: "5m",
    900: "15m",
    1800: "30m",
    3600: "1h",
    7200: "2h",
    14400: "4h",
    86400: "1d",
}

# ETH-USD is served by the ETHUSDT pair; Binance has no spot ETH/USD market. USDT trades
# close enough to par for MVP forecasting, and Coinbase's true ETH-USD book is the
# fallback. Revisit if the MVP ever depends on the USD peg holding exactly.
_SYMBOLS: Mapping[str, str] = {"ETH-USD": "ETHUSDT"}


class BinanceVisionProvider(MarketDataProvider):
    """Fetches klines from ``data-api.binance.vision``."""

    name: ClassVar[str] = "binance-vision"
    base_url: ClassVar[str] = "https://data-api.binance.vision"
    max_limit: ClassVar[int] = 1000

    def __init__(
        self,
        transport: HttpTransport = urllib_get,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_requests: int = 50,
    ) -> None:
        self._transport = transport
        self._timeout = timeout
        self._max_requests = max_requests

    def fetch_candles(
        self, asset: str, interval_seconds: int, start_time: int, end_time: int
    ) -> list[Candle]:
        symbol = _SYMBOLS.get(normalize_asset(asset))
        if symbol is None:
            raise ProviderError(f"{self.name} has no symbol mapping for {asset!r}")
        interval = _INTERVALS.get(interval_seconds)
        if interval is None:
            raise ProviderError(f"{self.name} does not serve a {interval_seconds}s interval")
        if end_time <= start_time:
            return []

        collected: list[Candle] = []
        cursor = start_time
        for _ in range(self._max_requests):
            if cursor >= end_time:
                break
            rows = self._request(symbol, interval, cursor, end_time)
            if not rows:
                break
            batch = [self._parse(row, interval_seconds) for row in rows]
            collected.extend(batch)
            cursor = max(candle.open_time for candle in batch) + interval_seconds
        else:
            raise ProviderError(
                f"{self.name} exceeded {self._max_requests} requests for {asset}; "
                "narrow the requested range"
            )

        return normalize_candles(
            collected,
            interval_seconds=interval_seconds,
            start_time=start_time,
            end_time=end_time,
        )

    def _request(self, symbol: str, interval: str, start_time: int, end_time: int) -> list[Any]:
        query = urlencode(
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": start_time * 1000,
                "endTime": end_time * 1000 - 1,
                "limit": self.max_limit,
            }
        )
        url = f"{self.base_url}/api/v3/klines?{query}"
        payload = self._transport(url, headers={}, timeout=self._timeout)
        try:
            decoded = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(f"{self.name} returned unparseable JSON: {exc}") from exc
        if not isinstance(decoded, list):
            raise ProviderError(f"{self.name} returned {type(decoded).__name__}, expected a list")
        return decoded

    def _parse(self, row: Any, interval_seconds: int) -> Candle:
        # [openTime_ms, open, high, low, close, volume, closeTime_ms, ...]
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            raise MalformedMarketDataError(f"{self.name} kline row is malformed: {row!r}")
        try:
            open_time_ms = int(row[0])
            return Candle(
                open_time=open_time_ms // 1000,
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                interval_seconds=interval_seconds,
            )
        except (TypeError, ValueError) as exc:
            raise MalformedMarketDataError(
                f"{self.name} kline row has non-numeric fields: {row!r}"
            ) from exc
