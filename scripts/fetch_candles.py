"""Live smoke check for the market-data layer. Not part of the test suite.

    python scripts/fetch_candles.py

Hits both venues for real, prints what each returned, and shows the failover chain and
volatility-derived return scale end to end.
"""

from __future__ import annotations

import time

from vanta.log import configure_logging, get_logger
from vanta.market.binance import BinanceVisionProvider
from vanta.market.coinbase import CoinbaseProvider
from vanta.market.errors import MarketDataError
from vanta.market.normalization import align_down
from vanta.market.provider import FailoverProvider
from vanta.market.resolution import ResolutionEngine

logger = get_logger(__name__)

ASSET = "ETH-USD"
INTERVAL = 60


def main() -> None:
    configure_logging("INFO")
    now = align_down(int(time.time()) - INTERVAL, INTERVAL)

    for provider in (BinanceVisionProvider(), CoinbaseProvider()):
        try:
            candles = provider.fetch_candles(ASSET, INTERVAL, now - 10 * INTERVAL, now)
        except MarketDataError as exc:
            print(f"{provider.name:16} FAILED  {exc}")
            continue
        last = candles[-1]
        print(
            f"{provider.name:16} {len(candles)} candles, "
            f"last close {last.close} @ {last.close_time}"
        )

    chain = FailoverProvider([BinanceVisionProvider(), CoinbaseProvider()])
    engine = ResolutionEngine(chain, candle_interval_seconds=INTERVAL)
    print(f"{'failover price':16} {engine.price_at(ASSET, now)}")
    print(f"{'15m return scale':16} {engine.return_scale(ASSET, now, 900):.6f}")


if __name__ == "__main__":
    main()
