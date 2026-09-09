"""Run a Vanta miner neuron against a Bittensor network.

    python scripts/run_miner.py --engine momentum --netuid 1 --network local \
        --wallet-name miner1 --wallet-hotkey default --port 8091

Serves the forecast endpoint over HTTP and publishes its ip:port on chain with the
ServeAxon intent. bittensor v11 has no axon server of its own — the HTTP layer is ours,
and only the identity (btauth/1 request signing) comes from the SDK.

The hotkey must already be registered on the subnet (`btcli subnet register`). Only the
hotkey is used here; the coldkey is never unlocked and never needs to be on this host.
"""

from __future__ import annotations

import argparse
import sys

from vanta.config import get_settings
from vanta.forecasting import (
    AdversarialEngine,
    MeanReversionEngine,
    MLEngine,
    MomentumEngine,
    PersistenceEngine,
    RandomEngine,
)
from vanta.forecasting.base import ForecastEngine
from vanta.log import configure_logging, get_logger
from vanta.market.binance import BinanceVisionProvider
from vanta.market.coinbase import CoinbaseProvider
from vanta.market.provider import FailoverProvider
from vanta.neurons import chain as chain_module
from vanta.neurons.miner import ForecastService, HotkeyGate, create_app, serve

logger = get_logger("scripts.run_miner")

ENGINES: dict[str, type[ForecastEngine]] = {
    "random": RandomEngine,
    "persistence": PersistenceEngine,
    "mean-reversion": MeanReversionEngine,
    "momentum": MomentumEngine,
    "ml": MLEngine,
    "adversarial": AdversarialEngine,
}


def build_engine(name: str) -> ForecastEngine:
    try:
        factory = ENGINES[name]
    except KeyError:
        raise SystemExit(f"unknown engine {name!r}; choose from {sorted(ENGINES)}") from None
    return factory()


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Vanta miner neuron")
    parser.add_argument("--engine", default=settings.miner_engine, choices=sorted(ENGINES))
    parser.add_argument("--netuid", type=int, default=settings.netuid)
    parser.add_argument("--network", default=settings.chain_network)
    parser.add_argument("--wallet-name", default=settings.wallet_name)
    parser.add_argument("--wallet-hotkey", default=settings.wallet_hotkey)
    parser.add_argument("--host", default=settings.axon_host)
    parser.add_argument("--port", type=int, default=settings.axon_port)
    parser.add_argument(
        "--announce-ip",
        default=settings.axon_announce_ip,
        help="public IP published on chain; defaults to not publishing",
    )
    parser.add_argument(
        "--min-stake",
        type=float,
        default=0.0,
        help="minimum caller stake (subnet units) before this miner will answer",
    )
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="serve unauthenticated (local testing only; never on a live subnet)",
    )
    args = parser.parse_args()

    configure_logging(settings.log_level)

    provider = FailoverProvider([BinanceVisionProvider(), CoinbaseProvider()])
    service = ForecastService(
        engine=build_engine(args.engine),
        provider=provider,
        candle_interval_seconds=settings.candle_interval_seconds,
        lookback_candles=settings.lookback_candles,
    )

    verifier = None
    gate = None
    if not args.no_auth:
        wallet = chain_module.load_wallet(args.wallet_name, args.wallet_hotkey)
        hotkey = chain_module.hotkey_address(wallet)
        chain = chain_module.connect(args.network, wallet)
        verifier = chain_module.make_verifier(hotkey)
        gate = HotkeyGate(chain, args.netuid, min_stake=args.min_stake)
        logger.info("miner hotkey %s on netuid %d (%s)", hotkey, args.netuid, args.network)

        if args.announce_ip:
            result = chain.serve_axon(args.netuid, args.announce_ip, args.port)
            logger.info("published axon %s:%d on chain: %s", args.announce_ip, args.port, result)
        else:
            logger.warning(
                "no --announce-ip given; this miner is not discoverable by validators "
                "until its endpoint is published on chain"
            )
    else:
        logger.warning("serving WITHOUT authentication - local testing only")

    app = create_app(service, gate=gate, verifier=verifier)
    logger.info("serving %s on %s:%d", args.engine, args.host, args.port)
    serve(app, args.host, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
