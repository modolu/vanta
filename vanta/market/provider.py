"""Normalized market-data domain objects and the provider interface (§13, §38).

Every venue is reduced to the same :class:`Candle` stream so providers stay swappable:
a miner or validator depends on :class:`MarketDataProvider`, never on a specific venue.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Protocol

from vanta.log import get_logger
from vanta.market.errors import (
    AllProvidersFailedError,
    MalformedMarketDataError,
    MarketDataError,
    ProviderError,
)
from vanta.validation import (
    VantaValidationError,
    require_non_negative,
    require_positive,
)

__all__ = [
    "Candle",
    "FailoverProvider",
    "HttpTransport",
    "MarketDataProvider",
    "urllib_get",
]

logger = get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10.0
USER_AGENT = "vanta/0.1 (+https://github.com/modolu/vanta)"


def _checked(validator, value: object, name: str) -> float:
    """Run a mechanism validator, re-raising as a market-data failure."""
    try:
        return validator(value, name)
    except VantaValidationError as exc:
        raise MalformedMarketDataError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class Candle:
    """One normalized OHLCV bar covering ``[open_time, open_time + interval_seconds)``."""

    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    interval_seconds: int

    def __post_init__(self) -> None:
        for field_name in ("open_time", "interval_seconds"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise MalformedMarketDataError(f"{field_name} must be an int, got {value!r}")
        if self.open_time < 0:
            raise MalformedMarketDataError(f"open_time must be >= 0, got {self.open_time!r}")
        if self.interval_seconds <= 0:
            raise MalformedMarketDataError(
                f"interval_seconds must be > 0, got {self.interval_seconds!r}"
            )

        for field_name in ("open", "high", "low", "close"):
            object.__setattr__(
                self, field_name, _checked(require_positive, getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "volume", _checked(require_non_negative, self.volume, "volume"))

        if self.high < max(self.open, self.close, self.low):
            raise MalformedMarketDataError(
                f"high {self.high} is below another price in candle at {self.open_time}"
            )
        if self.low > min(self.open, self.close, self.high):
            raise MalformedMarketDataError(
                f"low {self.low} is above another price in candle at {self.open_time}"
            )

    @property
    def close_time(self) -> int:
        """Unix timestamp at which this candle closes and its close price is final."""
        return self.open_time + self.interval_seconds


class HttpTransport(Protocol):
    """Minimal HTTP GET used by the venue providers, injectable so tests never hit the network."""

    def __call__(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> bytes:  # pragma: no cover - protocol
        ...


def urllib_get(url: str, *, headers: Mapping[str, str], timeout: float) -> bytes:
    """Default transport: a plain stdlib GET, so the project adds no HTTP dependency."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **dict(headers)})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"GET {url} failed with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"GET {url} failed: {exc}") from exc


class MarketDataProvider(ABC):
    """A source of normalized candles for a canonical asset such as ``ETH-USD``."""

    name: ClassVar[str] = "provider"

    @abstractmethod
    def fetch_candles(
        self, asset: str, interval_seconds: int, start_time: int, end_time: int
    ) -> list[Candle]:
        """Return candles with ``open_time`` in ``[start_time, end_time)``, ascending.

        The series is contiguous at ``interval_seconds`` and free of duplicates.

        Raises:
            MarketDataError: on transport failure, bad venue response, or a series that
                cannot be normalized.
        """


class FailoverProvider(MarketDataProvider):
    """Tries each provider in order, moving on when one fails (§13).

    Binance Vision is primary and Coinbase the fallback. Only :class:`MarketDataError`
    triggers failover; a programming error propagates immediately rather than being
    hidden behind a second venue.
    """

    name: ClassVar[str] = "failover"

    def __init__(self, providers: Sequence[MarketDataProvider]) -> None:
        if not providers:
            raise ValueError("FailoverProvider requires at least one provider")
        self._providers = tuple(providers)

    @property
    def providers(self) -> tuple[MarketDataProvider, ...]:
        return self._providers

    def fetch_candles(
        self, asset: str, interval_seconds: int, start_time: int, end_time: int
    ) -> list[Candle]:
        failures: list[str] = []
        for provider in self._providers:
            try:
                return provider.fetch_candles(asset, interval_seconds, start_time, end_time)
            except MarketDataError as exc:
                failures.append(f"{provider.name}: {exc}")
                logger.warning(
                    "provider %s failed for %s, falling back: %s", provider.name, asset, exc
                )
        raise AllProvidersFailedError(
            f"all providers failed for {asset} [{start_time}, {end_time}): " + "; ".join(failures)
        )
