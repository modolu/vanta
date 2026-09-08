# Vanta — permanent implementation rules

Vanta is a Bittensor subnet where miners publish calibrated probabilistic forecasts of future
market conditions, validators score them against realized outcomes, and weights follow measurable
forecasting quality. `ARCHITECTURE.md` is the source of truth; sections are cited as §N.

## Locked decisions

- **Python 3.12.** `bittensor` 11.1.0, added only when chain integration begins (Phase 5).
- **Asset: ETH/USD only** (§8). **Horizon: 15 minutes** for the MVP, but always configurable (§9).
- **Market data:** Binance `data-api.binance.vision` primary, Coinbase ETH-USD fallback, both behind
  one provider interface. `api.binance.com` and `fapi.binance.com` return HTTP 451 from this
  machine — do not use them. **No cross-venue median resolution yet** (§13 is future work).
- **Storage:** SQLite by default; every schema and query must stay PostgreSQL-compatible so the
  same code runs under Docker/testnet.
- Repo stays private until submission.

## Build order

0. Scaffold ✅
1. Core domain + scoring mechanism
2. Market data + resolution
3. Miner engines
4. Historical simulation
5. Bittensor integration
6. Testnet / submission

One phase at a time. Present a plan and get explicit approval before writing code for a new phase.
Never start the next phase unprompted.

## Rules

1. **Do not invent mechanism rules.** Scoring, reputation, weighting and consensus come from
   `ARCHITECTURE.md` (§15–§22, §30–§31). If a rule is ambiguous or missing, STOP and flag it rather
   than guessing — the mechanism is the project, and a silently invented rule corrupts it.
2. **No look-ahead, ever** (§29). A forecast engine may only see data at or before the task
   timestamp `T`; the outcome at `T + horizon` must be structurally unreachable, not merely
   un-consulted. Enforce this in the data-access API, not by convention.
3. **Determinism.** Given the same tasks, forecasts and resolution prices, scoring must produce
   identical results. Honest validators independently scoring the same task universe should agree
   (§24). Seed all randomness explicitly.
4. **Tests never touch the network.** Use recorded fixtures. Live API calls belong in scripts.
5. **Keep the protocol tiny** (§6). `probability_up` and `expected_return` are the required
   forecast fields; everything else is optional.
6. **Separate the Bittensor layer from the forecast engine** (§10). A miner operator must be able to
   replace their forecast engine without touching neuron code.
7. **Secrets** (§45): coldkeys never live on an application server or in this repo. `.env`,
   wallets and keys are gitignored.
8. **Verify before claiming done:** `ruff check .` and `pytest` must both be green.
9. Keep dependencies minimal. Justify every new one.

## Commands

```bash
source .venv/bin/activate
ruff check . && ruff format --check .
pytest
```

## Layout (§38)

`vanta/{protocol,forecasting,validator,market,consensus,api,database,neurons}` — plus
`vanta/config.py` and `vanta/log.py` for process configuration and logging. Tests mirror the
package under `tests/`.
