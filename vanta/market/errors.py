"""Failure modes of the market-data layer.

Separate from :class:`vanta.validation.VantaValidationError`: those signal a violated
mechanism invariant, these signal that the outside world did not give us usable data.
Both are always raised explicitly — the resolution engine must never silently substitute
a guess for a price, because that price becomes ground truth for every miner's score.
"""

from __future__ import annotations

__all__ = [
    "AllProvidersFailedError",
    "InsufficientMarketDataError",
    "LookaheadError",
    "MalformedMarketDataError",
    "MarketDataError",
    "ProviderError",
    "StaleMarketDataError",
]


class MarketDataError(Exception):
    """Base class for every market-data failure."""


class ProviderError(MarketDataError):
    """A single venue failed: transport error, bad status, or unparseable body."""


class MalformedMarketDataError(MarketDataError):
    """A venue returned data that violates the candle contract."""


class StaleMarketDataError(MarketDataError):
    """The freshest candle is too old to price the requested instant."""


class InsufficientMarketDataError(MarketDataError):
    """Not enough candles to answer the request."""


class LookaheadError(MarketDataError):
    """A causal view was asked to hold data from after its own instant (§29).

    This is always a bug, never a market condition: it means a forecast could have been
    computed from the outcome it was meant to predict.
    """


class AllProvidersFailedError(MarketDataError):
    """Every provider in the failover chain failed."""
