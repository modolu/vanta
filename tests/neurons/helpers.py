"""Offline doubles for the chain layer.

Nothing here imports ``bittensor`` and nothing touches the network. The neurons take
their chain access as protocols (:mod:`vanta.neurons.chain`), so the whole validator and
miner lifecycle can be exercised against these fakes.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence

from vanta.market.provider import Candle, MarketDataProvider
from vanta.neurons.chain import ChainError, NeuronRecord
from vanta.protocol.forecast import ForecastTask
from vanta.validator.collector import MinerQuery, TransportReply

T = 1_788_900_000  # 60-aligned reference instant
INTERVAL = 60
HORIZON = 900
WINDOW = 30


def make_task(
    *,
    timestamp: int = T,
    reference_price: float = 4500.0,
    horizon: int = HORIZON,
    window: int = WINDOW,
    asset: str = "ETH-USD",
) -> ForecastTask:
    return ForecastTask(
        task_id=f"{asset}-{horizon}s-{timestamp}",
        asset=asset,
        reference_price=reference_price,
        timestamp=timestamp,
        horizon_seconds=horizon,
        deadline=timestamp + window,
    )


def neuron(
    uid: int,
    hotkey: str,
    *,
    axon: str | None = None,
    validator_permit: bool = False,
    stake: float = 0.0,
) -> NeuronRecord:
    return NeuronRecord(
        uid=uid,
        hotkey=hotkey,
        axon=axon if axon is not None else f"127.0.0.1:{9000 + uid}",
        validator_permit=validator_permit,
        stake=stake,
    )


class FakeSubnetView:
    """A metagraph that can be reassigned between calls, to model uid churn."""

    def __init__(self, neurons: Sequence[NeuronRecord] = (), *, fail_with: str | None = None):
        self.neurons_by_round: list[Sequence[NeuronRecord]] = [list(neurons)]
        self.calls = 0
        self.fail_with = fail_with

    def set(self, neurons: Sequence[NeuronRecord]) -> None:
        self.neurons_by_round = [list(neurons)]

    def neurons(self, netuid: int) -> list[NeuronRecord]:
        self.calls += 1
        if self.fail_with is not None:
            raise ChainError(self.fail_with)
        return list(self.neurons_by_round[-1])


class FakeWeightSubmitter:
    """Records every weight vector it is handed; can be told to fail."""

    def __init__(self, *, fail_with: str | None = None) -> None:
        self.submissions: list[tuple[int, dict[int, float]]] = []
        self.fail_with = fail_with

    def set_weights(self, netuid: int, weights: Mapping[int, float]) -> str:
        if self.fail_with is not None:
            raise ChainError(self.fail_with)
        self.submissions.append((netuid, dict(weights)))
        return f"submitted {len(weights)} weights"

    @property
    def last(self) -> dict[int, float]:
        return self.submissions[-1][1]


class ScriptedTransport:
    """Returns a canned reply per uid, without any HTTP.

    ``replies`` maps uid -> payload (delivered on time), and ``late`` marks uids whose
    reply should be stamped after the task deadline.
    """

    def __init__(
        self,
        replies: Mapping[int, object],
        *,
        errors: Mapping[int, str] | None = None,
        late: Sequence[int] = (),
        received_at: float | None = None,
    ) -> None:
        self._replies = dict(replies)
        self._errors = dict(errors or {})
        self._late = set(late)
        self._received_at = received_at
        self.calls: list[tuple[str, bytes, Mapping[str, str]]] = []

    def post_all(
        self,
        calls: Sequence[tuple[MinerQuery, str, bytes, Mapping[str, str]]],
        *,
        timeout: float,
    ) -> list[TransportReply]:
        out: list[TransportReply] = []
        for miner, url, body, headers in calls:
            self.calls.append((url, body, headers))
            if miner.uid in self._errors:
                out.append(
                    TransportReply(
                        uid=miner.uid,
                        received_at=self._received_at or 0.0,
                        error=self._errors[miner.uid],
                    )
                )
                continue
            payload = self._replies.get(miner.uid)
            if payload is None:
                out.append(
                    TransportReply(
                        uid=miner.uid, received_at=self._received_at or 0.0, error="no reply"
                    )
                )
                continue
            when = self._received_at if self._received_at is not None else 0.0
            if miner.uid in self._late:
                when = when + 1_000_000.0
            out.append(TransportReply(uid=miner.uid, received_at=when, payload=payload))
        return out


class SeriesProvider(MarketDataProvider):
    """A market feed backed by an in-memory candle series. No network."""

    name = "test-series"

    def __init__(self, candles: Sequence[Candle]) -> None:
        self._candles = sorted(candles, key=lambda candle: candle.open_time)
        self.requests: list[tuple[str, int, int, int]] = []

    def fetch_candles(
        self, asset: str, interval_seconds: int, start_time: int, end_time: int
    ) -> list[Candle]:
        self.requests.append((asset, interval_seconds, start_time, end_time))
        return [
            candle
            for candle in self._candles
            if candle.interval_seconds == interval_seconds
            and candle.open_time >= start_time
            and candle.close_time <= end_time
        ]


def candles_from(closes: Sequence[float], *, start: int, interval: int = INTERVAL) -> list[Candle]:
    return [
        Candle(
            open_time=start + index * interval,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=10.0,
            interval_seconds=interval,
        )
        for index, close in enumerate(closes)
    ]


def drifting_closes(count: int, *, start: float = 4000.0, step: float = 0.5) -> list[float]:
    """A deterministic, gently trending series with enough variation for volatility."""
    wobble = itertools.cycle([0.0, 1.5, -1.0, 2.0, -0.5])
    closes: list[float] = []
    price = start
    for _ in range(count):
        price += step + next(wobble)
        closes.append(round(price, 4))
    return closes
