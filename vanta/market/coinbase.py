"""Coinbase Exchange market-data provider — the failover source (§13).

Coinbase serves a true ETH-USD book. Its candle endpoint differs from Binance in three
ways that :func:`normalize_candles` then erases: rows are ``[time, low, high, open,
close, volume]``, timestamps are in seconds, and the series is returned newest-first.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
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

__all__ = ["CoinbaseProvider"]

# The only granularities Coinbase Exchange accepts, in seconds.
_GRANULARITIES: frozenset[int] = frozenset({60, 300, 900, 3600, 21600, 86400})

_PRODUCTS: Mapping[str, str] = {"ETH-USD": "ETH-USD"}


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat().replace("+00:00", "Z")


class CoinbaseProvider(MarketDataProvider):
    """Fetches candles from ``api.exchange.coinbase.com``."""

    name: ClassVar[str] = "coinbase"
    base_url: ClassVar[str] = "https://api.exchange.coinbase.com"
    max_candles: ClassVar[int] = 300

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
        product = _PRODUCTS.get(normalize_asset(asset))
        if product is None:
            raise ProviderError(f"{self.name} has no product mapping for {asset!r}")
        if interval_seconds not in _GRANULARITIES:
            raise ProviderError(f"{self.name} does not serve a {interval_seconds}s granularity")
        if end_time <= start_time:
            return []

        collected: list[Candle] = []
        cursor = start_time
        span = self.max_candles * interval_seconds
        for _ in range(self._max_requests):
            if cursor >= end_time:
                break
            chunk_end = min(cursor + span, end_time)
            rows = self._request(product, interval_seconds, cursor, chunk_end)
            collected.extend(self._parse(row, interval_seconds) for row in rows)
            cursor = chunk_end
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

    def _request(self, product: str, granularity: int, start_time: int, end_time: int) -> list[Any]:
        query = urlencode(
            {
                "granularity": granularity,
                "start": _iso(start_time),
                # Coinbase treats `end` as inclusive of the candle starting at that
                # instant, so step back one second to keep the window half-open.
                "end": _iso(end_time - 1),
            }
        )
        url = f"{self.base_url}/products/{product}/candles?{query}"
        payload = self._transport(url, headers={}, timeout=self._timeout)
        try:
            decoded = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError(f"{self.name} returned unparseable JSON: {exc}") from exc
        if isinstance(decoded, dict) and "message" in decoded:
            raise ProviderError(f"{self.name} returned an error: {decoded['message']}")
        if not isinstance(decoded, list):
            raise ProviderError(f"{self.name} returned {type(decoded).__name__}, expected a list")
        return decoded

    def _parse(self, row: Any, interval_seconds: int) -> Candle:
        # [time_seconds, low, high, open, close, volume]
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            raise MalformedMarketDataError(f"{self.name} candle row is malformed: {row!r}")
        try:
            return Candle(
                open_time=int(row[0]),
                open=float(row[3]),
                high=float(row[2]),
                low=float(row[1]),
                close=float(row[4]),
                volume=float(row[5]),
                interval_seconds=interval_seconds,
            )
        except (TypeError, ValueError) as exc:
            raise MalformedMarketDataError(
                f"{self.name} candle row has non-numeric fields: {row!r}"
            ) from exc
