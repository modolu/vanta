# VANTA

### Decentralized market intelligence, earned by accuracy.

**One-line description**

> Vanta is a Bittensor subnet where independent forecasting models compete to predict future market conditions, validators score those forecasts against realized outcomes, and the network rewards miners according to measurable forecasting quality.

The important word here is **forecasting quality**, not trading profitability.

Vanta does not tell miners how to predict.

A miner could use:

- statistical models
- machine learning
- technical indicators
- order-book models
- on-chain data
- sentiment
- macroeconomic data
- proprietary datasets
- neural networks
- agentic systems
- ensembles

Vanta asks only:

> **How useful was the intelligence you produced?**

That is exactly the kind of “digital commodity” model Bittensor is designed for: miners produce useful work, validators measure its value, and validators submit weights that ultimately influence miner incentives. ([bittensor.com](https://www.bittensor.com/docs?utm_source=chatgpt.com))

---

# 1. The problem Vanta solves

Financial prediction today has a structural problem.

There are thousands of:

- trading models
- signals
- analysts
- forecasting APIs
- AI agents
- quantitative strategies
- social-media predictions

But determining which ones are genuinely useful is surprisingly difficult.

Someone can say:

> ETH is going to $5,000.

And if it happens once, they can advertise the prediction forever.

What we really want to know is:

> How frequently was this model correct?

> How confident was it when it was wrong?

> Is its probability calibration reliable?

> Does it consistently add information?

> Does it perform across different market regimes?

> Does it still perform outside the data on which it was developed?

There isn't an open, continuously competitive system that reliably answers these questions.

Vanta creates one.

---

# 2. The Vanta digital commodity

The commodity Vanta produces is:

## **Calibrated probabilistic market intelligence**

That distinction matters.

We're not selling:

> BUY ETH.

We're producing:

```text
ETH/USD
Horizon: 1 hour

Probability Up:       64%
Probability Down:     36%

Expected Return:      +0.32%

Expected Volatility:   0.91%

Network Confidence:   71%
```

This is much more useful to downstream systems.

An AI trading agent might decide:

```text
Vanta probability UP > 65%
+
my strategy confirms bullish structure
+
risk condition satisfied

→ execute
```

Another application might use it exclusively for risk.

A portfolio manager might use it as one input among twenty.

Vanta becomes **intelligence infrastructure**, not a trading bot.

---

# 3. Why Bittensor makes sense

The Vanta mechanism maps naturally onto Bittensor.

Bittensor subnets revolve around four main actors/concepts:

**miners** provide whatever useful commodity the subnet defines;

**validators** evaluate miner outputs and set weights;

the **subnet mechanism** defines what counts as useful work;

and **Yuma Consensus** aggregates validator evaluations into incentives/rewards while constraining manipulative weighting behaviour. ([bittensor.com](https://www.bittensor.com/docs/internals/consensus?utm_source=chatgpt.com))

For Vanta:

```text
MINER
produces market forecast
        │
        ▼
VALIDATOR
records forecast
        │
        ▼
TIME PASSES
        │
        ▼
MARKET OUTCOME
becomes ground truth
        │
        ▼
SCORING ENGINE
measures forecast quality
        │
        ▼
VALIDATOR WEIGHTS
reward better miners
```

That's unusually clean because **reality itself eventually provides our ground truth**.

---

# 4. High-level system architecture

I'd structure Vanta as six major layers.

```text
┌──────────────────────────────────────────────────────────┐
│                     VANTA TERMINAL                       │
│                                                          │
│ Forecasts │ Consensus │ Leaderboard │ Miner Analytics    │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                     VANTA API                            │
│                                                          │
│ /forecast                                                │
│ /consensus                                               │
│ /miners                                                  │
│ /history                                                 │
│ /performance                                             │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                VALIDATOR / INTELLIGENCE LAYER            │
│                                                          │
│ Task Generator                                            │
│ Forecast Collector                                        │
│ Resolution Engine                                         │
│ Scoring Engine                                            │
│ Reputation Engine                                         │
│ Consensus Aggregator                                      │
│ Weight Publisher                                          │
└─────────────┬──────────────────────────────┬─────────────┘
              │                              │
              │ Bittensor                    │ Market data
              ▼                              ▼
┌────────────────────────┐       ┌──────────────────────────┐
│    BITTENSOR SUBNET    │       │   MARKET DATA LAYER     │
│                        │       │                          │
│ Validators             │       │ Exchange APIs           │
│ Miners                 │       │ Oracle feeds            │
│ Axons                  │       │ DEX TWAPs                │
│ Metagraph              │       │ Price normalization      │
│ Weights                │       │ Resolution consensus     │
└───────────┬────────────┘       └──────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────┐
│                       MINERS                             │
│                                                          │
│ Momentum Miner                                           │
│ Mean Reversion Miner                                     │
│ ML Miner                                                 │
│ On-chain Miner                                           │
│ Ensemble Miner                                           │
│ Third-party Miner                                        │
└──────────────────────────────────────────────────────────┘
```

---

# 5. Core Bittensor architecture

The Bittensor layer is the heart of the project.

A miner in Bittensor is essentially a registered hotkey offering a service through its Axon endpoint; the subnet itself determines what useful work the miner must perform. Validators query miners and set weights according to the subnet's evaluation rules. ([preview.bittensor.com](https://preview.bittensor.com/docs/guides/validating?utm_source=chatgpt.com))

Our network will therefore have:

```text
Vanta Subnet
│
├── Validator 1
├── Validator 2
├── Validator 3
│
├── Miner 1
├── Miner 2
├── Miner 3
├── Miner 4
└── Miner N
```

For the hackathon we do **not** need hundreds.

Even the HackQuest example they highlight progressed with **3 validators and 10 miners**, specifically to demonstrate the fundamental miner-validator-incentive loop. ([hackquest.io](https://www.hackquest.io/hackathons/Bittensor-Global-Subnet-Hackathon))

For our MVP:

### Minimum

- 1 active validator
- 4–5 miners

### Strong submission

- 2–3 validators
- 5–10 miners

The important thing is not scale.

It's proving:

> good miners consistently earn better scores than bad miners.

---

# 6. Vanta Synapse

Miner-validator communication should use a clearly defined forecast request/response schema.

Conceptually, call it:

## `ForecastSynapse`

Validator sends:

```json
{
  "task_id": "eth-1h-20260920-1200",
  "asset": "ETH-USD",
  "reference_price": 4512.40,
  "timestamp": 1789905600,
  "horizon_seconds": 3600,
  "task_type": "direction_return",
  "deadline": 1789905630
}
```

Miner returns:

```json
{
  "task_id": "eth-1h-20260920-1200",
  "probability_up": 0.67,
  "expected_return": 0.0041,
  "expected_volatility": 0.0089,
  "confidence": 0.73,
  "model_version": "v3.1"
}
```

For the MVP, I would require only:

```text
probability_up
expected_return
```

Everything else is optional.

Keep the core protocol tiny.

---

# 7. Validator task-generation system

The validator needs a **Task Generator**.

Responsibilities:

1. choose asset;
2. choose forecast horizon;
3. fetch reference price;
4. create unique task;
5. timestamp task;
6. query active miners;
7. store predictions.

Example:

```text
Task Generator

asset:
ETH/USD

time:
12:00 UTC

reference:
$4,512

horizon:
60 minutes

submission window:
30 seconds
```

Then:

```text
Validator
   │
   ├── Miner A
   ├── Miner B
   ├── Miner C
   ├── Miner D
   └── Miner E
```

---

# 8. Which markets should Vanta predict?

For the MVP:

## Only ETH/USD.

Seriously.

Don't start with:

- ETH
- BTC
- TAO
- SOL
- gold
- equities
- Forex

One asset makes everything easier.

I would use:

### ETH/USD

because it's:

- liquid;
- relevant to Web3;
- easy to obtain market data for;
- volatile enough for meaningful forecasting;
- understandable to judges.

---

# 9. Forecast horizon

For a live hackathon demo, waiting one day for outcomes is terrible.

Use:

### 15-minute forecasts

and

### 60-minute forecasts.

The first gives us rapid experimentation.

The second tells a stronger forecasting story.

Architecture later supports:

```text
5m
15m
1h
4h
1d
```

But the MVP can use a single horizon.

---

# 10. Miner architecture

A miner should have two layers.

```text
┌─────────────────────────────┐
│      BITTENSOR MINER        │
│                             │
│ Axon                        │
│ Synapse handler             │
│ Request validation          │
│ Response formatter          │
└────────────┬────────────────┘
             │
             ▼
┌─────────────────────────────┐
│     FORECAST ENGINE         │
│                             │
│ Market data                 │
│ Feature extraction          │
│ Model                       │
│ Probability calibration     │
│ Return prediction           │
└─────────────────────────────┘
```

This separation is important.

Someone should eventually be able to replace:

```text
forecast_engine.py
```

without rewriting their Bittensor integration.

---

# 11. Baseline miners

Our demo should deliberately include different intelligence quality levels.

I'd implement five.

### Miner 1 — Random

```text
p(up) = random
return = random
```

Purpose:

**negative control.**

---

### Miner 2 — Persistence

Assumes recent price direction persists.

```text
recent return > 0
→ bullish probability
```

---

### Miner 3 — Mean Reversion

Large short-term moves increase probability of reversal.

---

### Miner 4 — Momentum

Uses indicators such as:

```text
EMA
ROC
RSI
recent returns
volatility
```

---

### Miner 5 — Simple ML

Something lightweight such as:

- logistic regression;
- gradient boosting;
- small neural network.

Features:

```text
return_1m
return_5m
return_15m
EMA difference
RSI
realized volatility
volume change
```

We do **not** need sophisticated AI to prove the subnet.

The subnet mechanism is the innovation.

---

# 12. Why miners shouldn't share methodology

Miners reveal:

> outputs.

Not:

> strategies.

That's valuable.

You can have:

```text
Miner A:
Bloomberg-like datasets

Miner B:
On-chain flows

Miner C:
technical models

Miner D:
social sentiment

Miner E:
deep neural net
```

The validator does not care.

It only measures performance.

This encourages competitive model innovation.

---

# 13. Market-data architecture

We have two separate market-data requirements.

## A. Miner data

Miners may obtain whatever data they want.

Their competitive advantage can come from better data.

## B. Validator ground truth

Validators need trustworthy resolution data.

This must be standardized.

For the MVP:

```text
Primary price source
         │
         ▼
Reference price
         │
         ▼
Resolution price
```

For production:

```text
Exchange A ───┐
Exchange B ───┼──► normalization ─► median price
DEX TWAP ─────┤
Oracle ───────┘
```

This reduces manipulation.

---

# 14. Resolution engine

Suppose task starts:

```text
12:00

ETH:
$4,500
```

Horizon:

```text
60 minutes
```

At:

```text
13:00
```

ETH trades:

```text
$4,545
```

Realized return:

```text
(4545 - 4500) / 4500
= +1%
```

Ground truth becomes:

```text
direction = UP
return = +0.0100
```

Now every forecast can be scored.

---

# 15. Vanta scoring system

This is arguably the most important part of the entire project.

I would call it:

# Vanta Score

For MVP:

```text
Vanta Score =
60% probability score
+
30% return accuracy
+
10% reliability adjustment
```

Eventually we can make it more sophisticated.

---

# 16. Probability score

Use a **Brier score**.

If:

```text
p = probability market rises
y = actual result
```

where:

```text
y = 1 if UP
y = 0 if DOWN
```

then:

```text
Brier = (p - y)²
```

Lower is better.

Convert into quality:

```text
ProbabilityQuality = 1 - Brier
```

Example:

Miner predicts:

```text
70% up
```

Market goes up:

```text
(0.70 - 1)² = 0.09
quality = 0.91
```

Miner predicts:

```text
99% up
```

Market falls:

```text
(0.99 - 0)² = 0.9801
quality = 0.0199
```

So Vanta punishes unjustified certainty.

That's exactly what we want.

---

# 17. Return accuracy

Suppose miner predicts:

```text
+0.7%
```

Actual:

```text
+1%
```

Error:

```text
|0.007 - 0.010|
= 0.003
```

But raw absolute errors need normalization.

Use:

```text
ReturnScore =
exp(-|predicted - actual| / scale)
```

Where scale represents normal market volatility.

This gives a smooth score from 0–1.

---

# 18. Calibration

Calibration measures whether stated probabilities correspond to reality.

If a miner says:

```text
70% UP
```

100 times, approximately:

```text
70 of them
```

should go up.

If only:

```text
40
```

go up, the miner is badly calibrated.

Calibration is extremely valuable in financial systems because:

> knowing how uncertain a model is can be nearly as valuable as knowing its prediction.

For hackathon scoring, calibration should be a **rolling metric**, not task-by-task.

---

# 19. Vanta reputation

Each miner maintains historical state.

```text
Miner UID: 17

Last 10:
0.82

Last 50:
0.76

Calibration:
0.91

Return accuracy:
0.71

Overall:
0.79
```

Use an EMA:

```text
R_t =
α × current_score
+
(1 - α) × R_(t-1)
```

For example:

```text
α = 0.1
```

This ensures:

- one lucky prediction doesn't dominate;
- old performance gradually matters less;
- miners must stay good.

---

# 20. Cold-start problem

New miners shouldn't be permanently disadvantaged.

Give new miners an initialization period.

For example:

```text
First 10 forecasts:

provisional score
```

During probation:

- they receive limited weight;
- performance builds their reputation;
- once minimum sample size is achieved, normal scoring applies.

---

# 21. Validator-to-Bittensor weight conversion

Validators don't directly distribute TAO however we want.

They evaluate miners and submit weights.

Bittensor's consensus and emissions machinery uses validator weights, validator stake and subnet consensus to derive miner incentives. ([bittensor.com](https://www.bittensor.com/docs/internals/consensus?utm_source=chatgpt.com))

Vanta therefore converts miner reputation into a normalized weight vector.

Example:

```text
Raw Vanta Scores

Miner A   .81
Miner B   .72
Miner C   .54
Miner D   .31
Miner E   .15
```

Apply transformation:

```text
weight_i ∝ score_i^γ
```

where:

```text
γ > 1
```

emphasizes quality differences.

Then normalize:

```text
Σ weights = 1
```

Example:

```text
Miner A   35%
Miner B   28%
Miner C   20%
Miner D   11%
Miner E    6%
```

Validator submits those weights.

---

# 22. Why not winner-take-all?

Because that creates unstable incentives.

If only rank #1 earns anything:

- miners become extremely aggressive;
- small variance dominates;
- new miners struggle to enter;
- useful diversity disappears.

Better:

> proportional but nonlinear rewards.

Better intelligence earns substantially more, while competent secondary models can still survive.

---

# 23. Yuma Consensus

This is the Bittensor-level protection layer.

Individual validators submit their own miner weight vectors.

Bittensor's Yuma Consensus uses stake-weighted consensus over validator weights, with clipping mechanisms intended to constrain manipulative validator behaviour. ([bittensor.com](https://www.bittensor.com/docs/internals/consensus?utm_source=chatgpt.com))

So conceptually:

```text
Validator A ─┐
Validator B ─┼──► Yuma Consensus ─► miner incentives
Validator C ─┘
```

Vanta defines:

> **how a validator should measure miner utility.**

Bittensor handles:

> **how competing validator opinions ultimately influence emissions.**

Important distinction.

---

# 24. Multiple validators

For the hackathon, validators should ideally evaluate the **same resolved task universe**.

Example:

```text
Task ID:
ETH-1H-123

Validator A:
Miner 4 = 0.82

Validator B:
Miner 4 = 0.80

Validator C:
Miner 4 = 0.83
```

Because the resolution rule and scoring equations are deterministic, honest validators should produce very similar scores.

That's actually a strong property of Vanta.

---

# 25. Anti-gaming system

This is where we can gain serious mechanism-design points.

## Attack 1 — Random guessing

Defense:

Rolling scoring destroys it over time.

---

## Attack 2 — Always predict UP

Defense:

Brier scoring and return-error scoring.

---

## Attack 3 — Extreme confidence

Example:

```text
99.9% UP
```

Defense:

Brier score heavily punishes wrong extreme probabilities.

---

## Attack 4 — Miner copying

Potential defense:

### hidden peer responses

Validators query miners independently.

For stronger future protection:

### commit/reveal.

```text
Miner
  │
  ▼
hash(prediction + nonce)
  │
  ▼
commit
```

Then:

```text
prediction + nonce
```

after submission window closes.

---

# 26. Collusion

Suppose five miners are controlled by one person and all submit identical predictions.

We can calculate forecast similarity.

If two miners produce nearly identical sequences over hundreds of tasks:

```text
correlation ≈ 1.0
```

we may:

- flag them;
- reduce diversity bonuses;
- inspect them.

But be careful:

Two legitimately good strategies can agree.

So duplicate-output detection should not automatically slash rewards.

---

# 27. Late-response gaming

A miner may wait to see additional market movement before responding.

Defense:

Every task has a hard deadline.

Example:

```text
task issued:
12:00:00

deadline:
12:00:20
```

Late response:

```text
score = 0
```

Eventually incorporate latency.

---

# 28. Market manipulation

A miner might try to move the reference market near resolution.

For ETH, this is difficult if we're resolving against deep liquidity.

Production Vanta should:

- use several venues;
- use median prices;
- use TWAPs;
- reject abnormal venue divergence.

---

# 29. Data leakage

Miners must never receive future data accidentally.

Historical simulation must carefully cut datasets at timestamp:

```text
features ≤ T
```

and outcome:

```text
T + horizon
```

should not be accessible to simulated miner algorithms.

This is absolutely essential to demonstrate.

---

# 30. Vanta Consensus

Miner forecasts themselves have external economic value.

So validators can calculate a network consensus.

Not simple averaging.

Use reliability-weighted probability:

```text
P_consensus =
Σ(w_i × p_i) / Σ(w_i)
```

Example:

```text
Miner       p(UP)       reputation

A           0.72          .84
B           0.55          .61
C           0.81          .76
D           0.40          .23
```

Weighted consensus might become:

```text
67% UP
```

Vanta publishes that.

---

# 31. Consensus confidence

We can estimate network confidence using:

- weighted miner agreement;
- historical reliability;
- prediction dispersion;
- sample size.

Example:

```text
Probability UP:
68%

Confidence:
HIGH

Miner dispersion:
LOW
```

Versus:

```text
Probability UP:
51%

Confidence:
LOW

Miner disagreement:
HIGH
```

This is extremely useful.

Sometimes:

> “the network has no strong opinion”

is the correct answer.

---

# 32. Vanta API

Eventually the core business surface isn't necessarily the dashboard.

It's the API.

Example:

```http
GET /v1/forecast/ETHUSD?horizon=1h
```

returns:

```json
{
  "asset": "ETHUSD",
  "horizon": "1h",
  "probability_up": 0.67,
  "expected_return": 0.0038,
  "network_confidence": 0.74,
  "active_miners": 31,
  "timestamp": 1789905600
}
```

Consumers:

- AI agents;
- trading bots;
- portfolio systems;
- DeFi protocols;
- researchers.

Bittensor documentation itself notes that validators can serve as gateways between subnet intelligence and external applications, which fits this commercialization path well. ([preview.bittensor.com](https://preview.bittensor.com/docs/guides/validating?utm_source=chatgpt.com))

---

# 33. Vanta Terminal

The frontend should be beautiful but minimal.

Homepage:

```text
VANTA

DECENTRALIZED MARKET INTELLIGENCE


ETH / USD
$4,512.32


1H OUTLOOK

           67%
           UP

Expected Return
+0.38%

Network Confidence
74%


Miners
31

─────────────────────────

VANTA CONSENSUS
```

---

# 34. Leaderboard

Second screen:

```text
VANTA NETWORK

MINER RANKINGS

#   Miner       Score    Calibration

1   8H4...X1     .842       .91
2   Q3L...83     .791       .86
3   J91...F7     .758       .80
4   A73...K2     .702       .76
5   V17...P4     .691       .81
```

This instantly demonstrates:

> competition creates quality.

---

# 35. Miner detail screen

Click miner:

```text
MINER 17

Vanta Score
82.4

Directional accuracy
61%

Brier
0.174

Calibration
91%

Return error
0.38%

Last 50 forecasts
███████████████████
```

This becomes an open reputation layer for forecasting systems.

---

# 36. Internal backend

I'd use:

### Python

because:

- Bittensor SDK is Python-centric;
- ML ecosystem;
- pandas/numpy/scikit-learn;
- easy quant modelling.

---

### FastAPI

for:

```text
Vanta API
dashboard backend
statistics endpoints
```

---

### PostgreSQL

for persistent data.

Main tables:

```text
miners
tasks
forecasts
resolutions
scores
miner_reputation
validator_runs
consensus_forecasts
```

---

### Redis

optional.

Useful for:

- active tasks;
- cache;
- job state.

Not essential for hackathon.

---

# 37. Database architecture

Something like:

### `tasks`

```text
id
asset
reference_price
start_time
horizon
deadline
status
resolution_price
```

### `forecasts`

```text
id
task_id
miner_uid
probability_up
expected_return
submitted_at
latency_ms
```

### `scores`

```text
forecast_id
brier_score
return_score
calibration_component
total_score
```

### `miners`

```text
uid
hotkey
first_seen
model_version
status
```

### `miner_reputation`

```text
miner_uid
ema_score
calibration
forecast_count
last_updated
```

---

# 38. Service architecture

I'd split the backend like this:

```text
vanta/
│
├── neurons/
│   ├── miner.py
│   └── validator.py
│
├── protocol/
│   └── forecast.py
│
├── forecasting/
│   ├── base.py
│   ├── random.py
│   ├── momentum.py
│   ├── mean_reversion.py
│   └── ml.py
│
├── validator/
│   ├── task_generator.py
│   ├── collector.py
│   ├── resolver.py
│   ├── scorer.py
│   ├── reputation.py
│   └── weights.py
│
├── market/
│   ├── provider.py
│   ├── normalization.py
│   └── resolution.py
│
├── consensus/
│   └── aggregator.py
│
├── api/
│   ├── forecasts.py
│   ├── miners.py
│   └── leaderboard.py
│
├── database/
│
├── tests/
│
└── scripts/
```

That is clean enough to become a real open-source subnet repository.

---

# 39. Full data flow

Here is the entire Vanta lifecycle.

```text
                     ┌──────────────┐
                     │ MARKET DATA  │
                     └──────┬───────┘
                            │
                            ▼
                    reference price
                            │
                            ▼
                  ┌──────────────────┐
                  │ TASK GENERATOR   │
                  └────────┬─────────┘
                           │
                  ForecastSynapse
                           │
          ┌────────────────┼─────────────────┐
          ▼                ▼                 ▼
      MINER A           MINER B          MINER N
          │                │                 │
       model A          model B           model N
          │                │                 │
          └────────────────┼─────────────────┘
                           │
                       forecasts
                           │
                           ▼
                  ┌─────────────────┐
                  │ FORECAST STORE  │
                  └────────┬────────┘
                           │
                       wait Δt
                           │
                           ▼
                    MARKET RESOLVES
                           │
                           ▼
                  ┌─────────────────┐
                  │ RESOLUTION      │
                  │ ENGINE          │
                  └────────┬────────┘
                           │
                     ground truth
                           │
                           ▼
                  ┌─────────────────┐
                  │ SCORING ENGINE  │
                  └────────┬────────┘
                           │
                  per-miner scores
                           │
                           ▼
                  ┌─────────────────┐
                  │ REPUTATION      │
                  │ ENGINE          │
                  └────────┬────────┘
                           │
                     Vanta Scores
                           │
            ┌──────────────┴──────────────┐
            ▼                             ▼
   ┌────────────────┐           ┌────────────────┐
   │ WEIGHT ENGINE  │           │ CONSENSUS      │
   │                │           │ AGGREGATOR     │
   └───────┬────────┘           └───────┬────────┘
           │                            │
   validator weights             Vanta Forecast
           │                            │
           ▼                            ▼
   BITTENSOR/YUMA                  VANTA API
           │                            │
           ▼                            ▼
      incentives                 TERMINAL/AGENTS
```

---

# 40. Testing architecture

We need automated tests for the mechanism itself.

## Test 1

Random miner should score near baseline.

## Test 2

Perfect miner should dominate.

## Test 3

Overconfident incorrect miner should be heavily punished.

## Test 4

Well-calibrated miner should outperform equally accurate but poorly calibrated miner.

## Test 5

Late response gets zero.

## Test 6

Malformed response gets rejected.

## Test 7

One outlier forecast should not destroy network consensus.

## Test 8

Long-term performance outweighs one lucky forecast.

These tests will make the GitHub repository much more convincing.

---

# 41. Historical simulation

This is one of the smartest things we can build.

We don't have to wait weeks to prove the mechanism.

Run historical market replay.

For example:

```text
Historical ETH data
        ↓
10,000 forecast tasks
        ↓
five simulated miners
        ↓
Vanta scoring
        ↓
leaderboard evolution
```

Then demonstrate:

```text
After 10 forecasts:

random miner briefly ranks #2

After 100:
falls to #4

After 1,000:
falls to #5

competent miner:
consistently #1
```

That's fantastic evidence for:

> incentives behave as intended.

Which HackQuest explicitly requires in the testnet submission. ([hackquest.io](https://www.hackquest.io/hackathons/Bittensor-Global-Subnet-Hackathon))

---

# 42. Hackathon MVP architecture

Now, importantly:

We do **not** build all of the production architecture first.

For the hackathon, build:

```text
ETH
 │
 ▼
Price feed
 │
 ▼
Validator
 │
 ├── Random miner
 ├── Momentum miner
 ├── Mean reversion
 ├── ML miner
 └── Adversarial miner
 │
 ▼
Resolution
 │
 ▼
Vanta Score
 │
 ▼
Bittensor weights
 │
 ▼
Leaderboard
```

That's enough.

---

# 43. MVP feature checklist

### Must exist

- Bittensor miner;
- Bittensor validator;
- Forecast Synapse;
- ETH price feed;
- forecast persistence;
- task resolver;
- Brier scoring;
- return scoring;
- rolling reputation;
- validator weight generation;
- testnet interaction;
- at least four miners;
- leaderboard;
- simulation demonstrating incentives.

### Nice-to-have

- dashboard;
- consensus forecast;
- API;
- calibration chart;
- miner detail page.

### Definitely later

- multi-asset;
- sentiment;
- on-chain data;
- full agent integration;
- institutional APIs;
- sophisticated collusion detection;
- multi-oracle resolution;
- real trading.

---

# 44. Technical deployment architecture

For testnet:

```text
SERVER / VPS

Docker Compose

├── validator
├── miner-random
├── miner-momentum
├── miner-reversion
├── miner-ml
├── postgres
└── api
```

Frontend can be deployed separately.

Eventually:

```text
Independent miner operator A
Independent miner operator B
Independent miner operator C
Independent validator A
Independent validator B
Independent validator C
```

The whole purpose is decentralization.

---

# 45. Security boundaries

Important separation:

```text
Coldkey
   │
   └── never stored on application server

Hotkey
   │
   ├── miner
   └── validator
```

Bittensor distinguishes coldkeys used for ownership/funds from hotkeys used to operate subnet participants, including serving an Axon or setting weights. ([preview.bittensor.com](https://preview.bittensor.com/docs/concepts/network?utm_source=chatgpt.com))

So deployment servers should not contain valuable coldkey secrets.

---

# 46. Future architecture

Vanta Phase II:

```text
                         VANTA
                           │
          ┌────────────────┼─────────────────┐
          │                │                 │
         ETH              BTC              TAO
          │                │                 │
          └────────────────┼─────────────────┘
                           │
                 multi-horizon forecasts
                           │
             ┌─────────────┼──────────────┐
             ▼             ▼              ▼
            15m           1h              1d
                           │
                           ▼
                   Vanta Consensus
                           │
          ┌────────────────┼─────────────────┐
          │                │                 │
      AI Agents          DeFi             Traders
          │              Protocols           │
          └────────────────┼─────────────────┘
                           ▼
                    Intelligence API
```

---

# 47. Later miner specializations

Eventually miners can specialize.

For example:

### Technical miner

price structure / indicators.

### On-chain miner

wallet flows / exchange deposits.

### Derivatives miner

funding / OI / liquidation data.

### Sentiment miner

social/news signals.

### Macro miner

rates / inflation / FX / economic releases.

### Deep-learning miner

large proprietary model.

Vanta doesn't have to know how they work.

Their output is judged by reality.

That's arguably the project's biggest strength.

---

# 48. Long-term Vanta Score

We could eventually create something analogous to a credit rating for forecasting systems.

Example:

```text
MINER V7

Vanta Score
87.3

Forecasts
148,271

Calibration
A+

ETH
91

BTC
83

TAO
74

15m
92

1h
87

1d
71
```

Now model reputation becomes portable.

That could itself be valuable.

---

# 49. Business model

The subnet produces the intelligence.

The commercial layer can monetize access.

Potential structure:

### Free

delayed consensus.

### Pro API

real-time forecasts.

### Institutional

- high-throughput API;
- miner-level data;
- uncertainty distributions;
- historical datasets;
- bespoke horizons.

### AI-agent API

machine-to-machine market intelligence.

The subnet creates competition.

The API turns that competition into a product.

---

# 50. Why this could actually win

I think Vanta has four unusually strong properties.

### 1. Ground truth is objective

The future market outcome resolves the prediction.

Very little subjective judging is required.

---

### 2. Incentives are understandable

Better predictions → better score → higher validator weight → greater rewards.

Judges can understand it immediately.

---

### 3. Miners can genuinely innovate

The network does not prescribe the model.

Competition encourages better data and better forecasting systems.

---

### 4. The resulting commodity is useful

We're producing something other systems can consume.

Not just:

> miner ranking.

We're producing:

> decentralized probabilities about future market states.

---

# 51. HackQuest alignment

Their judging categories are:

- Mechanism & Incentive Design;
- Technical Implementation;
- Miner-Validator Architecture;
- Evaluation & Scoring Quality;
- Problem & Market Relevance;
- Bittensor Ecosystem Value;
- Scalability & Long-Term Potential. ([hackquest.io](https://www.hackquest.io/hackathons/Bittensor-Global-Subnet-Hackathon))

Vanta maps cleanly to each:

| Criterion | Vanta |
|---|---|
| Mechanism | Competition over objectively resolved forecasts |
| Implementation | Real Bittensor miner/validator network |
| Miner-validator architecture | Very clearly separated |
| Evaluation | Brier + return error + calibration |
| Market relevance | Financial intelligence has obvious demand |
| Bittensor value | New machine-intelligence commodity |
| Scalability | More assets, horizons, strategies and consumers |

And critically, HackQuest explicitly says **polish is not the priority; functional correctness and conceptual integrity are**. ([hackquest.io](https://www.hackquest.io/hackathons/Bittensor-Global-Subnet-Hackathon))

That means we should put 80% of our effort into:

> **miner → forecast → resolution → scoring → weights**

before touching fancy visualizations.

---

# The architecture I would actually build first

Strip everything down to this:

```text
                    VANTA MVP

                 ETH PRICE FEED
                       │
                       ▼
               ┌───────────────┐
               │   VALIDATOR   │
               │               │
               │ create task   │
               └───────┬───────┘
                       │
             ForecastSynapse
                       │
      ┌────────┬───────┼───────┬────────┐
      ▼        ▼       ▼       ▼        ▼
   RANDOM   MOMENTUM   ML   REVERSION  BAD
   MINER     MINER   MINER   MINER    MINER
      │        │       │       │        │
      └────────┴───────┼───────┴────────┘
                       │
                    forecasts
                       │
                       ▼
                  WAIT 15 MIN
                       │
                       ▼
               MARKET RESOLUTION
                       │
                       ▼
                VANTA SCORING
                       │
                       ▼
              ROLLING REPUTATION
                       │
               ┌───────┴────────┐
               ▼                ▼
        BITTENSOR WEIGHTS    CONSENSUS
               │                │
               ▼                ▼
         MINER REWARDS       VANTA API
                                │
                                ▼
                          VANTA TERMINAL
```

**That is Vanta.**

Everything else is an expansion of that loop.

And if we're trying to win rather than merely submit, I would make the **forecast/scoring/incentive mechanism the star of the project**. Bittensor's current documentation explicitly frames subnet creators as the people who decide what miners should produce and how validators should score that commodity; the mechanism itself is off-chain code that the subnet operators implement. ([preview.bittensor.com](https://preview.bittensor.com/docs/guides/subnets?utm_source=chatgpt.com))

So the next logical step is no longer ideation. It's to convert this architecture into the **actual repository/build plan**: exact folders, dependencies, database schema, ForecastSynapse classes, scoring equations, validator pseudocode, miner pseudocode, test cases, Docker setup, and a **Day 1 → Day 4 coding sequence** so we can start implementing Vanta without architecture decisions being made on the fly.
