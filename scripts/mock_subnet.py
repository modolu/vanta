"""Offline end-to-end proof of the Phase 5 integration — no chain node, no internet.

    python scripts/mock_subnet.py [--rounds 12] [--miners 4]

What is real here:

* four miner neurons, each an actual uvicorn HTTP server on localhost, each running a
  different forecast engine;
* real btauth/1 request signing and verification using the installed Bittensor SDK's own
  sr25519 crypto, with receiver binding and replay protection;
* the real validator loop: task generation, concurrent fan-out over httpx, deadline
  enforcement, SQLite persistence, resolution, scoring, reputation and the weight vector.

What is faked, and only this:

* the chain itself — the metagraph is a static neuron list and weights are captured
  instead of submitted, because there is no subtensor node;
* market data — a deterministic synthetic candle series, so the run is reproducible and
  touches no external API.

Ephemeral development keypairs are generated in memory. No wallet file is written and no
coldkey exists anywhere in this process (§45).
"""

from __future__ import annotations

import argparse
import contextlib
import socket
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import uvicorn

from vanta.database.sqlite import SqliteValidatorStore
from vanta.forecasting import (
    MeanReversionEngine,
    MLEngine,
    MomentumEngine,
    PersistenceEngine,
    RandomEngine,
)
from vanta.forecasting.base import ForecastEngine
from vanta.log import configure_logging, get_logger
from vanta.market.provider import Candle, MarketDataProvider
from vanta.market.resolution import ResolutionEngine
from vanta.neurons.chain import NeuronRecord, make_signer, make_verifier
from vanta.neurons.miner import ForecastService, create_app
from vanta.neurons.validator import Validator, ValidatorConfig
from vanta.validator.collector import ForecastCollector, HttpxTransport
from vanta.validator.task_generator import TaskGenerator
from vanta.validator.weight_adapter import MinerRegistry

logger = get_logger("scripts.mock_subnet")

INTERVAL = 60
HORIZON = 900
WINDOW = 30
ENGINES: list[ForecastEngine] = [
    PersistenceEngine(),
    MeanReversionEngine(),
    MomentumEngine(),
    MLEngine(),
    RandomEngine(seed=7),
]


def synthetic_closes(count: int, *, start: float = 4000.0, seed: int = 11) -> list[float]:
    """A deterministic pseudo-random walk. Seeded explicitly, no RNG state shared."""
    closes: list[float] = []
    price = start
    state = seed
    for _ in range(count):
        state = (1_103_515_245 * state + 12_345) % (2**31)
        step = ((state / (2**31)) - 0.5) * 12.0
        price = max(100.0, price + step)
        closes.append(round(price, 4))
    return closes


class SyntheticProvider(MarketDataProvider):
    """An offline market feed. Deterministic and identical for every neuron."""

    name = "synthetic"

    def __init__(self, candles: Sequence[Candle]) -> None:
        self._candles = sorted(candles, key=lambda candle: candle.open_time)

    def fetch_candles(
        self, asset: str, interval_seconds: int, start_time: int, end_time: int
    ) -> list[Candle]:
        return [
            candle
            for candle in self._candles
            if candle.interval_seconds == interval_seconds
            and candle.open_time >= start_time
            and candle.close_time <= end_time
        ]


def build_candles(start: int, closes: Sequence[float]) -> list[Candle]:
    return [
        Candle(
            open_time=start + index * INTERVAL,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=10.0,
            interval_seconds=INTERVAL,
        )
        for index, close in enumerate(closes)
    ]


class StaticSubnet:
    """A metagraph that never changes, and a weight submitter that records."""

    def __init__(self, neurons: Sequence[NeuronRecord]) -> None:
        self._neurons = list(neurons)
        self.submissions: list[dict[int, float]] = []

    def neurons(self, netuid: int) -> list[NeuronRecord]:
        return list(self._neurons)

    def set_weights(self, netuid: int, weights: Mapping[int, float]) -> str:
        self.submissions.append(dict(weights))
        return f"captured {len(weights)} weights (no chain in this proof)"


@dataclass
class MinerProcess:
    """One running miner: its engine, keypair, port and server thread."""

    uid: int
    engine_name: str
    hotkey: str
    port: int
    server: uvicorn.Server
    thread: threading.Thread

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_miner(
    uid: int, engine: ForecastEngine, provider: MarketDataProvider, keypair: object
) -> MinerProcess:
    hotkey = keypair.ss58_address  # type: ignore[attr-defined]
    app = create_app(
        ForecastService(
            engine=engine,
            provider=provider,
            candle_interval_seconds=INTERVAL,
            lookback_candles=400,
        ),
        verifier=make_verifier(hotkey),
    )
    port = free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name=f"miner-{engine.name}")
    thread.start()

    deadline = time.monotonic() + 15.0
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError(f"miner {engine.name} failed to start on port {port}")

    return MinerProcess(
        uid=uid, engine_name=engine.name, hotkey=hotkey, port=port, server=server, thread=thread
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Vanta offline end-to-end proof")
    parser.add_argument("--rounds", type=int, default=12)
    parser.add_argument("--miners", type=int, default=4)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    configure_logging(args.log_level)

    try:
        from bittensor.sp_core import Keypair
    except ImportError:
        print("this proof needs the chain extra: pip install -e '.[chain]'")
        return 1

    miner_count = max(1, min(args.miners, len(ENGINES)))
    engines = ENGINES[:miner_count]

    # A candle series covering every task instant and its resolution.
    span = 400 + args.rounds * (HORIZON // INTERVAL) + (HORIZON // INTERVAL) + 10
    base = 1_700_000_000 - (1_700_000_000 % INTERVAL)
    provider = SyntheticProvider(build_candles(base, synthetic_closes(span)))
    first_task_at = base + 400 * INTERVAL

    validator_key = Keypair.create_from_uri("//Validator")
    miner_keys = [Keypair.create_from_uri(f"//Miner{index}") for index in range(miner_count)]

    logger.info("starting %d miner neurons over real HTTP", miner_count)
    miners = [
        start_miner(uid, engine, provider, key)
        for uid, (engine, key) in enumerate(zip(engines, miner_keys, strict=True))
    ]

    subnet = StaticSubnet(
        [
            NeuronRecord(
                uid=miner.uid,
                hotkey=miner.hotkey,
                axon=f"127.0.0.1:{miner.port}",
                validator_permit=False,
                stake=1.0,
            )
            for miner in miners
        ]
    )

    now = float(first_task_at)

    def clock() -> float:
        return now

    resolution = ResolutionEngine(provider, candle_interval_seconds=INTERVAL)
    store = SqliteValidatorStore(":memory:")
    registry = MinerRegistry()
    validator = Validator(
        config=ValidatorConfig(
            netuid=1,
            asset="ETH-USD",
            horizon_seconds=HORIZON,
            task_interval_seconds=HORIZON,
            weight_interval_seconds=1,
            self_hotkey=validator_key.ss58_address,
        ),
        generator=TaskGenerator(
            resolution=resolution,
            asset="ETH-USD",
            horizon_seconds=HORIZON,
            submission_window_seconds=WINDOW,
            clock=clock,
        ),
        collector=ForecastCollector(
            # The transport stamps replies from the simulated clock, so the §27 deadline
            # check compares like with like. The btauth freshness window still runs on
            # the real wall clock inside the SDK.
            HttpxTransport(clock=clock),
            signer=make_signer(validator_key),
            timeout_seconds=10.0,
            clock=clock,
        ),
        resolution=resolution,
        registry=registry,
        store=store,
        view=subnet,
        submitter=subnet,
        clock=clock,
    )

    issued = resolved = scored = 0
    try:
        for round_index in range(args.rounds):
            neurons = validator.sync()
            task, rejected = validator.issue_task(validator.miners(neurons))
            if task is not None:
                issued += 1
            if rejected:
                logger.warning("round %d rejections: %s", round_index, rejected)

            now += HORIZON + 1
            for outcome in validator.resolve_due():
                resolved += 1
                scored += outcome.scored

            validator.submit_weights(neurons, force=True)
    finally:
        for miner in miners:
            miner.stop()

    print()
    print("VANTA - OFFLINE END-TO-END PROOF")
    print("=" * 78)
    print(f"miners (real HTTP servers)  {len(miners)}")
    print(f"tasks issued                {issued}")
    print(f"tasks resolved              {resolved}")
    print(f"forecast scorings           {scored}")
    print(f"weight submissions captured {len(subnet.submissions)}")
    print(f"unresolved tasks remaining  {len(store.pending_tasks())}")
    print()

    final = subnet.submissions[-1] if subnet.submissions else {}
    snapshot = registry.snapshot()
    print(f"{'UID':>4}  {'ENGINE':<16} {'REPUTATION':>10} {'WEIGHT':>9}  HOTKEY")
    print("-" * 78)
    for miner in sorted(miners, key=lambda m: final.get(m.uid, 0.0), reverse=True):
        print(
            f"{miner.uid:>4}  {miner.engine_name:<16} "
            f"{snapshot.get(miner.hotkey, 0.0):>10.4f} "
            f"{final.get(miner.uid, 0.0):>9.4f}  {miner.hotkey[:16]}..."
        )
    print("-" * 78)
    print(f"weights sum to {sum(final.values()):.6f}")
    print()

    store.close()
    ok = issued > 0 and resolved > 0 and scored > 0 and bool(final)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(main())
