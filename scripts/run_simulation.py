"""Run the baseline historical replay and print the leaderboard evidence.

    python scripts/run_simulation.py [--max-tasks N] [--report PATH]

Reads candles from the on-disk cache populated by scripts/fetch_history.py.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from vanta.forecasting import default_engines
from vanta.log import configure_logging
from vanta.market.cache import HistoricalCandleCache
from vanta.simulation.leaderboard import render_report
from vanta.simulation.replay import DatasetInfo, SimulationConfig, run_simulation
from vanta.simulation.series import CandleSeries

ASSET = "ETH-USD"
INTERVAL = 60
CACHE_ROOT = "data/candles"
SOURCE = "binance-vision (data-api.binance.vision), coinbase fallback"


def main() -> int:
    parser = argparse.ArgumentParser(description="Vanta historical replay")
    parser.add_argument("--max-tasks", type=int, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--cache", type=str, default=CACHE_ROOT)
    args = parser.parse_args()

    configure_logging("INFO")
    candles = HistoricalCandleCache(args.cache).load(ASSET, INTERVAL)
    if not candles:
        print(f"no cached candles in {args.cache}; run scripts/fetch_history.py first")
        return 1

    series = CandleSeries(candles, interval_seconds=INTERVAL)
    dataset = DatasetInfo(
        source=SOURCE,
        symbol=ASSET,
        interval_seconds=INTERVAL,
        start_time=series.start_time,
        end_time=series.end_time,
        candle_count=len(series),
    )
    result = run_simulation(
        series,
        default_engines(),
        SimulationConfig(max_tasks=args.max_tasks),
        dataset,
    )

    report = render_report(result)
    print(report)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
