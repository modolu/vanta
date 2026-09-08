Recorded responses from the live venues, captured 2026-09-08, trimmed to three candles.

- `binance_klines_1m.json` — `GET data-api.binance.vision/api/v3/klines?symbol=ETHUSDT&interval=1m`
  Rows: `[openTime_ms, open, high, low, close, volume, closeTime_ms, ...]`, ascending.
- `coinbase_candles_60s.json` — `GET api.exchange.coinbase.com/products/ETH-USD/candles?granularity=60`
  Rows: `[time_seconds, low, high, open, close, volume]`, **descending**.

They exist so the provider parsers are tested against each venue's real field layout and
ordering. No test performs network I/O.
