"""Download historical ETH candles into the on-disk cache.

    python scripts/fetch_history.py [days]

Uses the existing provider/cache stack — no new data source. Safe to re-run: cached
ranges are served from disk, so an interrupted download resumes where it stopped.
"""

from __future__ import annotations

import sys
import time

from vanta.log import configure_logging, get_logger
from vanta.market.binance import BinanceVisionProvider
from vanta.market.cache import HistoricalCandleCache
from vanta.market.coinbase import CoinbaseProvider
from vanta.market.errors import MarketDataError
from vanta.market.normalization import align_down
from vanta.market.provider import FailoverProvider

logger = get_logger(__name__)

ASSET = "ETH-USD"
INTERVAL = 60
CACHE_ROOT = "data/candles"
CHUNK_CANDLES = 1000


def main(days: int) -> int:
    configure_logging("INFO")
    cache = HistoricalCandleCache(CACHE_ROOT)
    # Deliberately not wrapped in CachedProvider here: that writes the whole series back
    # to disk after every chunk, which is quadratic over a multi-week download. Chunks
    # are accumulated in memory and committed once.
    provider = FailoverProvider([BinanceVisionProvider(), CoinbaseProvider()])

    end = align_down(int(time.time()) - INTERVAL, INTERVAL)
    start = end - days * 86_400
    span = CHUNK_CANDLES * INTERVAL

    collected = list(cache.load(ASSET, INTERVAL))
    have = {candle.open_time for candle in collected}

    cursor = start
    failures = 0
    chunks = 0
    while cursor < end:
        chunk_end = min(cursor + span, end)
        if all(t in have for t in range(cursor, chunk_end, INTERVAL)):
            cursor = chunk_end
            continue
        try:
            fetched = provider.fetch_candles(ASSET, INTERVAL, cursor, chunk_end)
            collected.extend(c for c in fetched if c.open_time not in have)
            have.update(c.open_time for c in fetched)
            chunks += 1
            if chunks % 10 == 0:
                logger.info("fetched %d chunks, %d candles", chunks, len(collected))
        except MarketDataError as exc:
            failures += 1
            logger.warning("chunk [%s, %s) failed: %s", cursor, chunk_end, exc)
            if failures > 40:
                logger.error("too many failures, stopping")
                break
        cursor = chunk_end

    cache.extend(ASSET, INTERVAL, collected)
    stored = cache.load(ASSET, INTERVAL)
    if not stored:
        print("no candles cached")
        return 1
    print(
        f"cached {len(stored)} candles  "
        f"{stored[0].open_time} -> {stored[-1].close_time}  "
        f"({(stored[-1].close_time - stored[0].open_time) / 86400:.1f} days)  "
        f"failures={failures}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 60))
