"""Offline transports and candle builders for the market-data tests.

Nothing here touches the network: every provider under test is handed a fake transport
that replays recorded fixtures or canned payloads.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from vanta.market.provider import Candle

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "market"


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class RecordedTransport:
    """Replays a queue of canned responses and records the URLs it was asked for."""

    def __init__(self, responses: Sequence[bytes | Exception]) -> None:
        self._responses = list(responses)
        self.urls: list[str] = []

    def __call__(self, url: str, *, headers: Mapping[str, str], timeout: float) -> bytes:
        self.urls.append(url)
        if not self._responses:
            return b"[]"
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def json_response(payload: object) -> bytes:
    return json.dumps(payload).encode("utf-8")


def make_candle(open_time: int, close: float, *, interval: int = 60, **overrides: float) -> Candle:
    """A well-formed candle whose OHLC bracket always contains ``close``."""
    values: dict[str, float] = {
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 10.0,
    }
    values.update(overrides)
    return Candle(open_time=open_time, interval_seconds=interval, **values)  # type: ignore[arg-type]


def make_series(start: int, closes: Sequence[float], *, interval: int = 60) -> list[Candle]:
    """A contiguous candle series starting at ``start``."""
    return [
        make_candle(start + index * interval, close, interval=interval)
        for index, close in enumerate(closes)
    ]
