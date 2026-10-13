# Vanta Product Brief

## 1. Product Summary

**Vanta — decentralized market intelligence, earned by accuracy.**

Vanta is a Bittensor subnet where independent forecasting models compete to predict short-horizon market outcomes. Miners submit probabilistic forecasts for ETH/USD, validators compare those forecasts with what the market actually does, and the network rewards miners according to measurable forecasting quality rather than popularity, trading profit, or self-reported performance.

The core output is not a trade signal. Vanta produces **calibrated probabilistic market intelligence**: a probability of price direction, an expected return, reliability evidence from historical scoring, and a transparent track record showing how well each model has performed over time.

For the hackathon MVP, Vanta focuses on one market — ETH/USD — and one primary horizon — 15 minutes — so the full miner → forecast → resolution → scoring → reputation → Bittensor weights loop can be demonstrated clearly and repeatedly.

---

## 2. Problem

Financial forecasting is crowded with models, analysts, APIs, agents, indicators, and social-media predictions, but it is difficult to know which sources are genuinely useful.

A forecaster can make one dramatic correct call and advertise it indefinitely. What users actually need to know is:

- How often is this model correct?
- How confident is it when it is wrong?
- Are its probabilities calibrated?
- Does it consistently add information?
- Does performance hold up across many observations rather than a few lucky calls?
- Can different models be compared under the same objective rules?

Most forecasting products do not provide an open, continuous, incentive-aligned system for answering those questions.

Vanta creates that system by letting reality provide the ground truth and using transparent scoring rules to convert forecast quality into reputation and network incentives.

---

## 3. Target Users

### Primary user: autonomous trading or risk agent developer

A developer building an AI trading agent, portfolio system, or risk engine needs a market-intelligence input that is:

- machine-readable;
- probabilistic rather than binary;
- continuously evaluated;
- transparent about uncertainty;
- resistant to one-off lucky predictions;
- sourced from competing independent models rather than one opaque provider.

Vanta gives that developer a consensus forecast backed by a live reputation system.

### Secondary users

- quantitative researchers;
- discretionary traders who want a confidence layer rather than another signal;
- DeFi protocols that need market-risk inputs;
- portfolio/risk systems;
- forecasting-model developers who want to compete and earn based on measurable performance.

---

## 4. Product Promise

Vanta answers one simple question:

> **How useful was the intelligence a forecasting model produced?**

Instead of asking miners to reveal their strategy, training data, or proprietary model, Vanta only evaluates their outputs.

A miner may use technical indicators, machine learning, order-book data, on-chain data, macro data, sentiment, proprietary datasets, ensembles, or any other forecasting method. Vanta does not prescribe the methodology.

It measures the result.

---

## 5. Why Bittensor

Vanta fits Bittensor because forecasting creates objective, repeatable ground truth.

The network loop is:

1. A validator creates a forecast task.
2. Registered miners submit forecasts before a hard deadline.
3. The market moves.
4. The validator resolves the task using real market data.
5. Each miner is scored under the same deterministic rules.
6. Historical performance updates the miner's reputation.
7. Reputation is converted into validator weights.
8. Bittensor turns validator weights into miner incentives.

The subnet therefore defines the digital commodity and the evaluation mechanism, while Bittensor supplies the decentralized incentive layer.

Vanta's digital commodity is:

> **Calibrated probabilistic market intelligence.**

---

## 6. MVP Product Experience

### Vanta Terminal

The judge-facing product surface is a minimal terminal/dashboard that makes the network understandable in seconds.

The primary screen should show:

- ETH/USD reference price;
- current 15-minute probability of UP/DOWN;
- expected return;
- miner dispersion / agreement (the MVP does not invent a separate network-confidence score);
- number of active miners;
- latest consensus forecast;
- current Bittensor subnet status.

### Miner leaderboard

A second view ranks miners by measurable quality, including:

- Vanta Score;
- EMA reputation;
- Brier / probability quality;
- calibration;
- return accuracy;
- current validator weight;
- forecast count.

### Miner detail

A lightweight detail view can show:

- public miner identity;
- current score and rank;
- historical performance;
- recent forecasts;
- directional accuracy;
- calibration;
- return error.

The purpose of the UI is not trading execution. It is to make the subnet mechanism and the resulting intelligence legible to users and judges.

---

## 7. Core Forecast Protocol

For the MVP, each task contains:

- asset: ETH/USD;
- reference price;
- task timestamp;
- 15-minute forecast horizon;
- submission deadline;
- unique task ID.

Each miner must return:

- `probability_up`;
- `expected_return`.

Optional metadata may include model version, volatility estimate, or confidence, but the core protocol remains intentionally small.

---

## 8. Vanta Score

Each resolved forecast receives a Vanta Score composed of three parts:

### 60% — Probability quality

Vanta uses a Brier-derived probability score:

`ProbabilityQuality = 1 - (p - y)^2`

This rewards accurate probabilities and heavily punishes unjustified certainty.

### 30% — Return accuracy

The expected return is compared with realized return using a volatility-normalized exponential score:

`ReturnScore = exp(-abs(predicted_return - actual_return) / scale)`

The scale is derived from observed ETH volatility rather than an arbitrary fixed constant.

### 10% — Calibration

Calibration measures whether stated probabilities match long-run outcomes. A miner that repeatedly says "70% UP" should be right roughly 70% of the time.

The MVP uses a rolling calibration score so miners build a reputation over many forecasts rather than being judged by a single event.

---

## 9. Reputation and Incentives

Vanta maintains a rolling reputation for each miner using an exponential moving average of forecast quality.

This means:

- one lucky prediction does not dominate;
- old performance gradually matters less;
- miners must continue producing useful forecasts;
- extreme but unreliable models lose standing over time.

Reputation is converted into a normalized Bittensor weight vector using nonlinear proportional weighting. Better miners receive meaningfully more weight without collapsing the subnet into winner-take-all rewards.

Live reputation is keyed by miner hotkey, not reusable UID, so a newly registered miner cannot inherit the reputation of a previous miner that occupied the same UID.

---

## 10. Consensus Forecast

Vanta does not simply average miner predictions.

The network consensus is reliability-weighted:

`P_consensus = sum(weight_i * probability_i) / sum(weight_i)`

A miner with a stronger verified track record therefore contributes more to the network forecast than an unreliable miner.

This makes the final Vanta forecast a product of competition and historical evidence rather than equal voting.

---

## 11. Anti-Gaming Design

The MVP explicitly addresses common forecasting-network attacks:

- **Random guessing:** rolling scoring causes random performance to decay toward baseline.
- **Always-UP predictions:** probability, return, and calibration scoring expose the strategy over time.
- **Extreme confidence:** Brier scoring heavily punishes confident errors.
- **Late-response gaming:** forecasts arriving after the task deadline are discarded.
- **Look-ahead leakage:** miners receive a structurally bounded market context containing only information available at task time.
- **UID recycling:** reputation follows hotkey identity, not UID slots.
- **Peer copying:** miners are queried independently and do not receive peer responses.

Future versions may add commit/reveal for miner forecasts and more advanced collusion detection.

---

## 12. Baseline Miner Set

The hackathon includes multiple deliberately different forecasting engines so the incentive mechanism has real variation to evaluate:

1. Random — negative control.
2. Persistence — assumes recent movement continues.
3. Mean reversion — fades short-term moves.
4. Momentum — combines recent returns, EMA structure, RSI/ROC, and volatility.
5. Lightweight ML — deterministic logistic/linear models over historical features.
6. Adversarial — deliberately overconfident, used to prove that the scoring system punishes bad certainty.

These are mechanism baselines, not claims of proprietary alpha.

---

## 13. Evidence So Far

### Historical simulation

Vanta has already been replayed over 60 days of real 1-minute ETH market data:

- 78,760 candles;
- 5,722 tasks attempted;
- 5,195 valid resolved tasks;
- six miner strategies evaluated under the same rules.

The baselines showed roughly chance directional accuracy, which is reported honestly. The important result is that Vanta still separated miners on calibration and return quality: random and deliberately overconfident strategies received materially lower reputation and weights than the honest forecasting engines.

The reliability-weighted consensus also achieved a better Brier score than any individual baseline miner in that replay.

### Local Bittensor proof

The full network path has been proven against a real local subtensor chain:

- registered neurons;
- on-chain endpoint publication;
- metagraph discovery;
- signed HTTP requests;
- forecast collection;
- resolution and scoring;
- persistence;
- reputation;
- UID-aligned weights;
- accepted on-chain weight submission.

### Public testnet

A dedicated Bittensor public testnet subnet has been created for Vanta:

- netuid: **564**;
- validator owner registered at UID 0;
- subnet activated;
- validator staked;
- remaining live-network work is miner registration and completion of the public forecast-to-weight cycle.

---

## 14. Hackathon MVP Scope

### Must-have

- real Bittensor validator;
- at least four registered miners;
- live ETH/USD market feed;
- forecast task creation;
- signed miner requests/responses;
- persistence across the 15-minute resolution window;
- task resolution;
- Brier/probability scoring;
- return scoring;
- rolling calibration and reputation;
- reputation-to-weight conversion;
- public testnet weight submission;
- historical simulation proof;
- judge-facing leaderboard / Vanta Terminal.

### Nice-to-have

- miner detail page;
- calibration visualization;
- historical consensus chart;
- polished network-status panel;
- public read-only API documentation.

### Explicitly out of scope for the hackathon

- multi-asset support;
- live trading/execution;
- institutional billing/API plans;
- complex social/news sentiment miners;
- sophisticated collusion detection;
- multi-oracle median/TWAP resolution;
- production-scale multi-validator decentralization;
- mobile application.

---

## 15. Demo Flow

A convincing live demo should take less than two minutes:

1. Open Vanta Terminal and show the current ETH/USD 15-minute outlook.
2. Show four live miners on Vanta's Bittensor testnet subnet.
3. Open the current task and show each miner's probability and expected return.
4. Show a resolved historical/live task and its realized market outcome.
5. Show the Vanta Score breakdown and resulting leaderboard/reputation.
6. Show the generated Bittensor weight vector.
7. Show the testnet subnet/metagraph and the corresponding on-chain weight transaction/commit.
8. End on the consensus forecast: decentralized market intelligence produced by competing models and earned by accuracy.

---

## 16. Success Criteria

The hackathon MVP is successful when a judge can verify, without trusting a marketing claim, that:

1. multiple miners independently produce forecasts;
2. forecasts are resolved against objective market outcomes;
3. poor calibration and bad certainty are measurably punished;
4. sustained forecast quality produces better reputation;
5. reputation changes Bittensor validator weights;
6. the system runs on a real Bittensor testnet subnet;
7. the resulting consensus forecast is consumable as useful machine intelligence.

---

## 17. Why Vanta Can Win

Vanta aligns strongly with the HackQuest judging criteria:

- **Mechanism & Incentive Design:** rewards are tied directly to objectively resolved forecast quality.
- **Technical Implementation:** the core mechanism, simulation, signed networking, persistence, local-chain proof, and public subnet are real implementations rather than mock concepts.
- **Miner-Validator Architecture:** miner methodology is independent; validators evaluate outputs under deterministic shared rules.
- **Evaluation & Scoring Quality:** Brier scoring, return accuracy, calibration, reputation, and anti-gaming behavior are explicit and testable.
- **Problem & Market Relevance:** forecasting quality is a clear problem for trading agents, portfolio systems, and risk infrastructure.
- **Bittensor Ecosystem Value:** Vanta introduces a reusable machine-intelligence commodity rather than a closed trading application.
- **Scalability & Long-Term Potential:** the same mechanism can expand to more assets, horizons, miner specializations, validators, and downstream API consumers.

The central pitch is simple:

> **Vanta turns competing market forecasts into a continuously measured, reputation-weighted intelligence network — and lets Bittensor reward the models that prove useful over time.**

---

## 18. Product Principle

Vanta does not need to prove that its hackathon baseline miners can predict ETH better than professional trading firms.

It needs to prove something more fundamental:

> **If useful forecasting intelligence exists, Vanta can identify it, measure it, aggregate it, and reward it objectively.**

That mechanism is the product.
