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
- **Mechanism decisions locked after Phase 1** — change only on explicit instruction:
  - An exactly flat realized return (`0.0`) **voids** the directional outcome (§14). Void tasks are
    excluded from scoring, calibration and reputation; they never count as DOWN.
  - Rolling calibration is **10-bin ECE**, `quality = 1 - ECE`, for the MVP (§18).
  - Weight exponent **`gamma = 1.2`**, configurable (§21).
  - **`provisional_scale = 1.0`** — no probation penalty until simulation evidence justifies one (§20).
  - Return-score **`scale` is derived from observed ETH volatility**, never hard-coded arbitrarily (§17).
  - **Network confidence (§31) stays deferred** — its ingredients are named but not its equation.
- Repo stays private until submission.

## Build order

0. Scaffold ✅
1. Core domain + scoring mechanism ✅
2. Market data + resolution ✅
3. Miner engines ✅
4. Historical simulation ✅
5. Bittensor integration ✅ (localnet-proven)
6. Testnet / submission — **in progress as the completion sprint below**

One phase at a time. Present a plan and get explicit approval before writing code for a new phase.
**Do not start a future phase unless explicitly instructed.**

## Completion sprint (approved) — deadline 2026-10-15 23:59 UTC+1

`PROGRESS.md` is the live task tracker. Work its tasks in order, keep exactly one task
`IN PROGRESS`, and update it whenever a task's status, a decision, or a known issue changes.
Scope below is approved; anything not listed is out of scope until explicitly instructed.

**Must-have**

- **Testnet netuid 564 verified live** — the dedicated Vanta subnet: owner/validator UID,
  activation, validator stake and permit, registration burn — read from chain, not assumed.
- **≥4 miners** registered on netuid 564, serving signed endpoints validators can reach.
- **One real 15-minute forecast-to-weight cycle on the public testnet**, with evidence: task,
  per-miner forecasts, resolution, score breakdown, reputation, UID-aligned weight vector, and the
  accepted weight extrinsic/commit event. Evidence is recorded output, never paraphrase.
- **Minimal Vanta Terminal** (§33–§34): ETH/USD reference price, latest consensus
  `probability_up` and `expected_return`, active miner count, subnet status, and the leaderboard.
  Network confidence (§31) stays deferred — show miner dispersion only if its definition is
  already in code; never invent a confidence number.
- **Vercel deployment** of the Terminal frontend.
- **Submission docs**: README and `docs/` updated to verified live facts, demo flow, evidence index.

**Nice-to-have** (only after every must-have is done): miner detail (§35), forecast/score history,
live refresh.

**Cut** (do not build, do not scaffold): trading/execution, multi-asset, new strategy tuning,
PostgreSQL, Redis, multiple validators, collusion detection system, cross-venue oracle,
authentication, mobile.

**Runtime stays as is**: Python 3.12, `bittensor` 11.1.0, signed FastAPI (miner) / httpx
(validator) neuron stack, SQLite storage.

**Demo data**: the historical simulation (`make fetch-history && make simulation`) is the
reproducible demo-data path, alongside real testnet output. Do not add a seed command or
fabricated fixture data for presentation.

## Frontend and presentation layer

Direction: **Next.js + TypeScript, read-only presentation layer deployed on Vercel.** It displays
mechanism output; it never computes scores, weights or consensus, and never writes. **Do not
scaffold it until its task is explicitly started.**

- **Shared typed presentation schemas.** One set of Pydantic response models in `vanta/api/` is
  the contract. The frontend mirrors them in a single TypeScript types module, field-for-field;
  a change to either side updates both in the same change. Presentation schemas are separate
  from the `ForecastSynapse` wire protocol, which stays locked.
- **Validate at every boundary.** The API validates what it serves through those models; the
  frontend validates each response shape at its fetch boundary before rendering. Untrusted or
  malformed data becomes the error state, never a crash or a silently wrong number.
- **Consistent errors.** One error shape, defined once in the presentation schemas, used by every
  endpoint and handled by one frontend code path.
- **Every data view has loading, empty and error states.** "No resolved tasks yet" is a real
  state, not a blank screen.
- **Config via environment.** Backend keeps `VANTA_`-prefixed settings in `vanta/config.py` and
  `.env.example`; the frontend reads its API base URL from env. No hard-coded hosts or netuids.
- **No secrets in the client.** Anything shipped to the browser (including every `NEXT_PUBLIC_*`
  variable) is public. No keys, tokens, wallet material or private hostnames in the frontend.
- **No new dependencies without explicit approval** — Python or npm, including UI, chart, state
  or validation libraries. This tightens mechanism rule 7 for the sprint.
- **Small functions and components**: one responsibility each; format and derive values in plain
  typed helpers, not inline in markup.
- **Critical-path tests only** for presentation code: schema contract, boundary validation,
  error/empty handling. No snapshot or visual tests. Mechanism test standards are unchanged.

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
