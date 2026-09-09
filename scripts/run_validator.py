"""Run a Vanta validator neuron against a Bittensor network.

    python scripts/run_validator.py --netuid 1 --network local \
        --wallet-name validator --wallet-hotkey default

Each round: sync the metagraph, resolve any task whose horizon has elapsed, issue a new
task to every serving miner, score what comes back, and submit weights.

State is persisted, so a restart inside the forecast horizon resumes its in-flight tasks
rather than losing them. Only the hotkey is used; the coldkey is never unlocked.
"""

from __future__ import annotations

import argparse
import sys

from vanta.config import get_settings
from vanta.database.sqlite import SqliteValidatorStore
from vanta.log import configure_logging, get_logger
from vanta.market.binance import BinanceVisionProvider
from vanta.market.coinbase import CoinbaseProvider
from vanta.market.provider import FailoverProvider
from vanta.market.resolution import ResolutionEngine
from vanta.neurons import chain as chain_module
from vanta.neurons.validator import Validator, ValidatorConfig
from vanta.validator.collector import ForecastCollector, HttpxTransport
from vanta.validator.task_generator import TaskGenerator
from vanta.validator.weight_adapter import MinerRegistry

logger = get_logger("scripts.run_validator")


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Vanta validator neuron")
    parser.add_argument("--netuid", type=int, default=settings.netuid)
    parser.add_argument("--network", default=settings.chain_network)
    parser.add_argument("--wallet-name", default=settings.wallet_name)
    parser.add_argument("--wallet-hotkey", default=settings.wallet_hotkey)
    parser.add_argument("--database", default=settings.database_url)
    parser.add_argument(
        "--task-interval",
        type=int,
        default=settings.horizon_seconds,
        help="seconds between issued tasks (default: one horizon)",
    )
    parser.add_argument("--weight-interval", type=int, default=360)
    parser.add_argument(
        "--max-rounds", type=int, default=None, help="stop after N rounds (default: run forever)"
    )
    args = parser.parse_args()

    configure_logging(settings.log_level)

    wallet = chain_module.load_wallet(args.wallet_name, args.wallet_hotkey)
    hotkey = chain_module.hotkey_address(wallet)
    chain = chain_module.connect(args.network, wallet)
    logger.info("validator hotkey %s on netuid %d (%s)", hotkey, args.netuid, args.network)

    provider = FailoverProvider([BinanceVisionProvider(), CoinbaseProvider()])
    resolution = ResolutionEngine(
        provider, candle_interval_seconds=settings.candle_interval_seconds
    )

    store = SqliteValidatorStore.from_url(args.database)
    pending = store.pending_tasks()
    if pending:
        logger.info("resuming with %d unresolved task(s) from a previous run", len(pending))

    validator = Validator(
        config=ValidatorConfig(
            netuid=args.netuid,
            asset=settings.asset,
            horizon_seconds=settings.horizon_seconds,
            task_interval_seconds=args.task_interval,
            weight_interval_seconds=args.weight_interval,
            self_hotkey=hotkey,
        ),
        generator=TaskGenerator(
            resolution=resolution,
            asset=settings.asset,
            horizon_seconds=settings.horizon_seconds,
            submission_window_seconds=settings.submission_window_seconds,
        ),
        collector=ForecastCollector(
            HttpxTransport(),
            signer=chain_module.make_signer(wallet),
            timeout_seconds=settings.request_timeout_seconds,
        ),
        resolution=resolution,
        registry=MinerRegistry(),
        store=store,
        view=chain,
        submitter=chain,
    )

    try:
        rounds = validator.run(max_rounds=args.max_rounds)
    except KeyboardInterrupt:
        logger.info("interrupted; shutting down")
        return 0
    finally:
        store.close()

    logger.info("completed %d round(s)", rounds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
