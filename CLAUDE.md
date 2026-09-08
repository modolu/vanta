# Vanta — permanent implementation rules

Vanta is a Bittensor subnet where miners publish calibrated probabilistic forecasts of future
market conditions, validators score them against realized outcomes, and weights follow measurable
forecasting quality. **`ARCHITECTURE.md` is the source of truth**; sections are cited as §N.

## Engineering stance

Work as a senior, production-focused full-stack/systems engineer.

- Prefer the **simplest correct implementation** that satisfies the current milestone. Solve today's
  milestone, not an imagined future one.
- **Match the existing architecture and conventions** of this repository rather than importing
  patterns from elsewhere.
- Write **complete, runnable, typed code with real error handling**. Type-annotate public functions
  and dataclasses; handle the failure paths you introduce.
- **No placeholders.** No stub implementations, fake integrations, mocked-out "working" code, or
  TODO logic presented as complete. If something cannot be finished, say so plainly instead of
  shipping a shell of it.
- **Flag problems as you find them**: bugs, security issues, data leakage, race conditions, unsafe
  assumptions, and unnecessary complexity — including in code you did not write.
- **Compare alternatives only when the choice materially matters**, and keep the comparison brief.
  Otherwise pick the sensible default and move on.
- **Do not modify unrelated files.**
- **Keep implementation reports concise**: what changed, what ran, what is blocked.

## Locked decisions

Do not silently change protocol schemas, scoring equations, architecture decisions, or MVP scope.
Changing any of these requires an explicit instruction — raise it, do not just do it.

- **Python 3.12.** `bittensor` 11.1.0, added only when chain integration begins (Phase 5).
- **ETH/USD only** for the MVP (§8). **15-minute default horizon**, always configurable (§9).
- **Required forecast outputs: `probability_up` and `expected_return`** (§6). Everything else in the
  synapse is optional. Keep the protocol tiny.
- **Market data:** Binance Vision (`data-api.binance.vision`) primary, Coinbase ETH-USD fallback,
  both behind one provider interface. `api.binance.com` and `fapi.binance.com` return HTTP 451 from
  this machine — do not use them. **No cross-venue median resolution yet** (§13 is future work).
- **Storage:** SQLite locally; every schema and query must stay PostgreSQL-compatible so the same
  code runs under Docker/testnet.
- **The local mechanism must be proven before Bittensor integration.** Scoring, reputation,
  weighting and consensus are demonstrated offline against historical replay first.
- **Mechanism correctness takes priority over API/UI polish** (§51 — polish is explicitly not the
  judging priority).
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
**Do not start a future phase unless explicitly instructed.**

## Mechanism rules

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
5. **Separate the Bittensor layer from the forecast engine** (§10). A miner operator must be able to
   replace their forecast engine without touching neuron code.
6. **Secrets** (§45): coldkeys never live on an application server or in this repo. `.env`, wallets
   and keys are gitignored.
7. Keep dependencies minimal. Justify every new one.

## Verification

Run the relevant tests and linting after every implementation, and verify before claiming done —
`ruff check .`, `ruff format --check .` and `pytest` must all be green.

```bash
source .venv/bin/activate
ruff check . && ruff format --check .
pytest
```

## Layout (§38)

`vanta/{protocol,forecasting,validator,market,consensus,api,database,neurons}` — plus
`vanta/config.py` and `vanta/log.py` for process configuration and logging. Tests mirror the
package under `tests/`.
