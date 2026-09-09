# Vanta

**Decentralized market intelligence, earned by accuracy.**

A Bittensor subnet where miners publish calibrated probabilistic forecasts of future market
conditions, validators score them against realized outcomes, and weights — therefore
emissions — follow measurable forecasting quality.

---

## 1. What Vanta is

Every 15 minutes a validator fixes a reference price for ETH/USD and asks every registered
miner one question:

> Where will this be in 15 minutes? Give me a probability and an expected return.

Miners answer with `probability_up` and `expected_return`. Fifteen minutes later the market
answers too, and the validator scores each miner against what actually happened. Good
forecasters accumulate reputation; bad and dishonest ones lose it. The reputation vector
becomes the validator's Bittensor weight vector.

Nothing about a miner's method is prescribed. The subnet only measures whether the
forecasts were right, and whether the stated confidence was honest.

## 2. Why Bittensor

Forecasting is unusually well suited to an incentive network because **it grades itself**.
There is no human labeller, no preference model, and no subjective rubric: the market
publishes ground truth on a fixed schedule, and a proper scoring rule turns that into a
number. A miner cannot argue with a Brier score.

That gives Bittensor exactly what it needs — an objective, cheap, non-gameable evaluation
that many independent validators compute identically and agree on without coordinating.

## 3. The digital commodity

Vanta produces **calibrated probabilistic market intelligence**: a continuously updated,
reputation-weighted consensus forecast with a track record attached.

The emphasis is on *calibrated*. A miner that says "70% up" must be right about 70% of the
time, or its calibration term decays. A confident coin-flipper and a hedged expert can post
the same directional accuracy; Vanta separates them.

## 4. Architecture

```
                    ETH/USD market data (Binance Vision -> Coinbase failover)
                                        |
                                  reference price
                                        |
                                 TASK GENERATOR  (validator)
                                        |
                             ForecastSynapse over signed HTTP
                    +-------------------+-------------------+
                    v                   v                   v
                MINER A             MINER B             MINER N
             forecast engine     forecast engine     forecast engine
                    |                   |                   |
                    +-------------------+-------------------+
                                        |
                              collected before deadline
                                        |
                                   [ persisted ]
                                        |
                            ... 15 minutes later ...
                                        |
                              RESOLUTION ENGINE  (realized price)
                                        |
                                  VANTA SCORING
                                        |
                                 ROLLING REPUTATION
                                        |
                              WEIGHTS (score^gamma, normalized)
                                        |
                                  BITTENSOR CHAIN
```

Layout (`ARCHITECTURE.md` §38):

| Package | Role |
|---|---|
| `vanta/protocol/` | domain models + the ForecastSynapse wire schema |
| `vanta/forecasting/` | the six reference engines, behind a leakage-proof context |
| `vanta/market/` | data providers, normalization, resolution engine |
| `vanta/validator/` | scoring, reputation, weights, task generation, collection |
| `vanta/consensus/` | reputation-weighted consensus forecast |
| `vanta/database/` | validator persistence interface + SQLite implementation |
| `vanta/neurons/` | the Bittensor miner and validator, and the single SDK boundary |

**One boundary rule matters most:** `vanta/neurons/chain.py` is the *only* module that
imports `bittensor`, and it imports it lazily. Everything else depends on protocols. The
entire mechanism installs, runs and tests without the chain SDK — enforced by a test.

### A note on Bittensor v11

`bittensor` 11 **removed the axon/dendrite/synapse networking stack**; `bt.Synapse`,
`bt.Axon` and `bt.Dendrite` no longer exist. Subnets now bring their own HTTP layer and
authenticate it with `bittensor.http_auth` (the `btauth/1` signed-request protocol),
publishing endpoints on chain with the `ServeAxon` intent.

Vanta follows that current design: miners are FastAPI services, validators are httpx
clients, every request is hotkey-signed with receiver binding and replay protection, and
discovery goes through the metagraph.

## 5. The Vanta Score

Per resolved forecast (`ARCHITECTURE.md` §15–§18):

```
Vanta Score = 0.60 * probability quality      (1 - Brier score)
            + 0.30 * return score             (exp(-|predicted - actual| / scale))
            + 0.10 * calibration component    (1 - ECE, rolling, 10 bins)
```

* **Probability quality** is the Brier score inverted. It rewards being right *and*
  being appropriately confident.
* **Return score** grades the magnitude call. `scale` is derived from **observed ETH
  volatility** at the task horizon, never hard-coded.
* **Calibration** is rolling and historical — it comes from the miner's reputation
  *before* this forecast, so a forecast never contributes to its own calibration term.

Reputation is an EMA (`alpha = 0.1`) of the Vanta Score. Weights are
`weight_i ∝ score_i ^ gamma` with `gamma = 1.2`, normalized to sum to 1 — emphasizing
quality differences without collapsing into winner-take-all (§21–§22).

An exactly flat realized return (`0.0`) **voids** the task: it is excluded from scoring,
calibration and reputation entirely, rather than being counted as DOWN (§14).

## 6. Miner / validator lifecycle

**Miner** — two strictly separated layers (§10). The neuron serves HTTP, verifies the
caller's hotkey signature, checks the caller is registered on the subnet, and formats the
response. It contains *zero* forecasting logic. Swapping the forecast engine requires no
neuron code changes.

**Validator** — one round:

1. sync the metagraph;
2. resolve and score any task whose 15-minute horizon has elapsed;
3. generate a new task at the current reference price;
4. query every serving miner concurrently, with signed requests;
5. drop late and malformed responses; persist the rest;
6. update reputation from the newly resolved tasks;
7. convert reputation to a UID-aligned weight vector and submit it.

Tasks persist across the horizon, so a validator restart mid-window resumes rather than
losing in-flight work.

## 7. The six baseline miner strategies

Deliberately spanning a range of quality, so the mechanism has something to separate (§11):

| Engine | Method |
|---|---|
| `random` | seeded noise — the floor |
| `persistence` | assumes the last move continues |
| `mean-reversion` | fades deviation from a rolling mean |
| `momentum` | trend continuation over a lookback window |
| `ml` | a small fitted model over engineered features |
| `adversarial` | deliberately miscalibrated — states extreme confidence to test the scoring rule |

`adversarial` exists to be punished. If the mechanism ranked it well, the mechanism would
be broken.

## 8. Anti-gaming design

| Attack (§25–§29) | Defense in this codebase |
|---|---|
| Random guessing | Brier + return scoring drives reputation to the floor |
| Always predict UP | calibration term decays; return score collapses |
| Extreme confidence | Brier punishes confident errors quadratically |
| Miner copying | validators query miners independently; peers never see each other's answers |
| **Late-response gaming** | hard per-task deadline; a response arriving after it is **discarded**, never scored |
| **Look-ahead / data leakage** | structural, not conventional: the forecast context drops every candle closing after `T`, so the outcome bar is unreachable even if the data provider returns it |
| Deregistration laundering | **reputation is keyed by hotkey, never by UID** — a recycled UID starts fresh and provisional |

That last row is subtle and easy to get wrong. On chain a UID is a recyclable *slot*: when a
miner deregisters, a different operator can be issued the same UID. Carrying reputation
across that boundary would credit a newcomer with a departed miner's record. Vanta stores
reputation under the hotkey and resolves the current UID from the metagraph at submission
time.

## 9. Historical simulation evidence

60 days of real 1-minute ETH/USD candles (78,760 candles), replayed through the full
mechanism: 5,722 tasks attempted, **5,195 valid**, 14 void (exactly flat), 513 unresolvable.
Full output in [`docs/BASELINE_RESULTS.txt`](docs/BASELINE_RESULTS.txt).

| # | Miner | Vanta Score | Reputation (EMA) | Brier | Calibration | **Weight** | Directional |
|---|---|---|---|---|---|---|---|
| 1 | momentum | 0.6676 | 0.7397 | 0.2944 | 0.8354 | **0.1973** | 48.3% |
| 2 | mean-reversion | 0.6978 | 0.7366 | 0.2686 | 0.8785 | **0.1963** | 51.0% |
| 3 | persistence | 0.6626 | 0.7288 | 0.2847 | 0.8586 | **0.1938** | 49.0% |
| 4 | ml | 0.6988 | 0.7174 | 0.2637 | 0.9127 | **0.1902** | 50.5% |
| 5 | random | 0.5394 | 0.5260 | 0.3303 | 0.7612 | **0.1311** | 50.8% |
| 6 | adversarial | 0.3636 | 0.3893 | 0.4823 | 0.5180 | **0.0913** | 50.8% |

**Read this honestly.** Every strategy, including the four genuine ones, landed at roughly
**chance directional accuracy** (46–51%) on this dataset. Vanta makes **no claim of
directional alpha**, and these baselines do not demonstrate any. 15-minute ETH direction is
close to a coin flip, and the baselines are simple by design.

What the run *does* demonstrate is that **the mechanism separates miners anyway**, on the
axes it is built to measure:

* `adversarial` — same 50.8% directional accuracy as `random`, but confidently wrong and
  wrong about magnitude — is driven to **0.0913 weight**, less than half the honest engines'.
* `random` lands at **0.1311**, clearly below the four genuine engines (0.190–0.197).
* The separation comes from **calibration** (0.518 for adversarial vs 0.83–0.91 for the
  honest engines) and **return quality** (0.0044 vs 0.49–0.57), not from direction.

That is the intended result: the incentive rewards honest, calibrated uncertainty even where
directional edge is absent. A miner with genuine alpha would separate further still.

Reproduce: `make fetch-history && make simulation` (the candle cache is not committed;
the fetch downloads it once). The replay is deterministic — re-running it reproduces every
figure in the table above to four decimal places, which is the §24 property that lets
independent validators agree without coordinating.

## 10. Localnet evidence — real chain, full cycle

The complete lifecycle proven against a **real subtensor node** (not a mock): registration,
on-chain endpoint publication, metagraph discovery, signed HTTP forecast requests,
resolution, scoring, reputation, UID-aligned weights, and an accepted `set_weights`
extrinsic.

```
netuid 1, 6 registered neurons, 4 miners queried over signed HTTP
tasks issued 3 | resolved 3 | forecast scorings 12
weight vector {2: 0.1912, 3: 0.3141, 4: 0.2150, 5: 0.2797}   (sums to 1.000000)
set_weights  success=True  extrinsic=163-0002
             events=['TimelockedWeightsCommitted','TransactionFeePaid','ExtrinsicSuccess']
```

Per-task forecasts, resolutions and per-miner score breakdowns:
[`docs/LOCALNET_EVIDENCE.md`](docs/LOCALNET_EVIDENCE.md).

Repeated runs against a fresh chain reproduce that weight vector **exactly** — the
mechanism is deterministic given the same tasks, forecasts and resolution prices (§24).

Reproduce:

```bash
make localnet-up
make localnet-proof
make localnet-down
```

This run also caught three real bugs that a mock could not have: unchecked extrinsic
results (the SDK reports rejection via `result.success`, not by raising), subnet stake being
alpha-denominated so `Balance.tao` raises on it, and the chain rejecting loopback addresses
in `serve_axon`.

## 11. Testnet status

**Not deployed.** Verified against the live public test network (read-only, free):
reachable at `wss://test.finney.opentensor.ai:443`, block ~7,968,889, spec 455,
registration burn 0.0005 τ/hotkey, netuid 1 tempo 99 with commit-reveal enabled.

Deployment is blocked on one thing: **this machine has no funded testnet coldkey, and
testnet TAO cannot be obtained programmatically.** btcli v11 has no `faucet` command, and
the SDK states the faucet extrinsic is disabled on every real network — funding requires a
human request via the Bittensor Discord faucet channel or a transfer from a funded wallet.

The full cost is only **~0.054 τ**. Everything needed to finish is written and tested;
[`docs/TESTNET.md`](docs/TESTNET.md) has the exact remaining commands. Check readiness at
any time with `make testnet-preflight` (spends nothing).

The identical code path is already proven against a real chain in §10 — the public testnet
adds a different endpoint and real registration economics, not different Vanta code.

## 12. Installation

Requires **Python 3.12** and (for the chain layer) Docker if you want the localnet proof.

```bash
make install
source .venv/bin/activate
```

The chain SDK is an **optional extra**. The mechanism, engines, simulation and most tests
run without it:

```bash
pip install -e .              # mechanism only
pip install -e '.[chain,dev]' # + bittensor 11.1.0, FastAPI, httpx, test tooling
```

## 13. Running a miner

```bash
python scripts/run_miner.py \
    --network test --netuid 1 \
    --wallet-name vanta --wallet-hotkey miner0 \
    --engine momentum --port 8091 --announce-ip <your public ip>
```

`--announce-ip` is published on chain so validators can find you; **the chain rejects
loopback**. Omit it to serve without advertising. Add `--min-stake` to refuse callers below
a stake threshold. `--no-auth` disables signature checking — local testing only.

To run your own strategy, implement `ForecastEngine.predict()` and pass it to
`ForecastService`. No neuron code changes.

## 14. Running a validator

```bash
python scripts/run_validator.py \
    --network test --netuid 1 \
    --wallet-name vanta --wallet-hotkey validator
```

Runs until interrupted. State persists to SQLite, so a restart inside the 15-minute horizon
resumes its in-flight tasks. `--weight-interval` must respect the subnet's weights rate
limit (100 blocks ≈ 20 min on testnet).

## 15. Configuration

Environment variables with the `VANTA_` prefix, or a `.env` file. See
[`.env.example`](.env.example) for every key.

| Key | Default | Meaning |
|---|---|---|
| `VANTA_ASSET` | `ETH-USD` | the only MVP asset (§8) |
| `VANTA_HORIZON_SECONDS` | `900` | forecast horizon (§9) |
| `VANTA_SUBMISSION_WINDOW_SECONDS` | `30` | miner deadline; must be < horizon |
| `VANTA_NETUID` / `VANTA_CHAIN_NETWORK` | `1` / `local` | subnet and network |
| `VANTA_WALLET_NAME` / `VANTA_WALLET_HOTKEY` | `default` | wallet **names**, never secrets |
| `VANTA_AXON_PORT` / `VANTA_AXON_ANNOUNCE_IP` | `8091` / unset | bind port and published IP |
| `VANTA_DATABASE_URL` | `sqlite:///data/vanta.db` | validator state |

## 16. Testing

```bash
make check      # ruff check + ruff format --check + pytest
```

**584 tests, no network access.** Every market response is a recorded fixture and every
chain interaction is a protocol double; live calls live in `scripts/`, never in tests.
Running the full suite needs the `[chain,dev]` extras (the neuron tests exercise the real
FastAPI app and the real `btauth` crypto); the mechanism packages themselves import and
run with `bittensor` absent, which is what the isolation test enforces.

Notable coverage: the structural no-look-ahead guarantee, late-response rejection, the
UID-recycling trap, real btauth signature/tamper/replay rejection, restart recovery, and a
subprocess test proving the mechanism imports with `bittensor` unavailable.

## 17. Security and key handling

* **Coldkeys never touch this repository or a running neuron.** Only hotkeys are used at
  runtime — to serve, to sign requests, and to sign the weight extrinsic (§45).
* Wallets live in the standard `~/.bittensor/wallets`. Configuration carries wallet
  *names*, never key material.
* `.env`, `wallets/`, `*.pem` are gitignored. No mnemonic, seed or private key appears
  anywhere in this repo, including in the proof scripts — those derive **ephemeral
  development keypairs in memory** for throwaway local chains.
* Miner endpoints authenticate every request: signature, receiver binding, freshness
  window and replay protection, plus a registered-hotkey gate.
* `scripts/testnet_register.py` refuses to run against mainnet.

## 18. Limitations

Stated plainly, because they matter more than polish:

* **No demonstrated directional alpha.** The baselines are at chance (§9). Vanta measures
  forecast quality; it does not claim to predict ETH.
* **Not deployed to public testnet** — blocked on faucet funding (§11).
* **Single asset, single horizon.** ETH/USD, 15 minutes.
* **Single-venue resolution.** Binance Vision with Coinbase failover; no cross-venue median
  (§13 future work), so resolution inherits one venue's print.
* **Network confidence (§31) is deferred** — its ingredients are named in the architecture
  but its equation is not, and inventing one would corrupt the mechanism.
* **`provisional_scale = 1.0`** — new miners get no probation penalty yet, because no
  simulation evidence yet justifies a specific value.
* **PostgreSQL is not implemented.** The schema is written to port cleanly, but only SQLite
  exists and is tested; the code depends on a storage interface, not on SQLite behaviour.
* **No dashboard, API or leaderboard UI.** Mechanism correctness was prioritized over
  polish (§51).
* Commit/reveal for miner responses (§25) is not implemented; independent querying is the
  current copying defense.

## 19. Roadmap

1. Fund a testnet coldkey and complete the public deployment (`docs/TESTNET.md`).
2. Cross-venue median resolution (§13) to remove single-venue dependence.
3. Calibrate `provisional_scale` from simulation evidence rather than leaving it at 1.0.
4. Define and implement network confidence (§31).
5. PostgreSQL store behind the existing interface; Docker Compose topology (§44).
6. Read-only API and leaderboard (§32–§34).
7. Additional assets and horizons, once the single-asset mechanism is proven live.

---

## Repository map

```
vanta/          the subnet: protocol, engines, market data, scoring, neurons
tests/          584 tests mirroring the package; no network access
scripts/        live-network tooling, proofs and runners
docs/           baseline results, localnet evidence, testnet status
ARCHITECTURE.md the source of truth; sections cited as §N throughout
CLAUDE.md       engineering rules and locked mechanism decisions
```

Useful commands:

```bash
make help               # list everything
make check              # lint + tests
make fetch-history      # download the 60-day candle cache (once)
make simulation         # 60-day historical replay
make mock-subnet        # offline end-to-end proof (no chain, no internet)
make localnet-proof     # full proof against a real local subtensor
make testnet-preflight  # testnet readiness; spends nothing
make network-state      # inspect a subnet's Vanta topology on chain
```
