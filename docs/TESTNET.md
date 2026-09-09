# Testnet deployment — status and exact remaining steps

This file records what was verified against the **public Bittensor test network**, what is
blocked, and the exact commands to finish the deployment. It is deliberately honest about
the boundary: everything below the "Blocked" line has **not** been executed, and nothing in
this repository claims otherwise.

Verified live on the test network on 2026-09-09.

---

## What was verified against the real test network

All of this is read-only and cost nothing.

| Fact | Value |
|---|---|
| Network label (v11) | `test` — still current, confirmed from `bittensor.settings.NETWORKS` |
| Endpoint | `wss://test.finney.opentensor.ai:443` |
| Reachable | yes, block ~7,968,889 |
| Runtime `spec_version` | 455 |
| Block time | 12.0s (not fast blocks) |
| Subnets present | 560 |
| Registration burn, netuid 1 | 0.0005 τ per hotkey |
| New-subnet lock cost | 1.0 τ |
| netuid 1 tempo | 99 |
| netuid 1 commit-reveal | **enabled** |
| netuid 1 weights rate limit | 100 blocks (~20 min at 12s) |
| netuid 1 min allowed weights | 1 |
| netuid 1 occupancy | 256 neurons, 90 publishing an endpoint |

Reproduce with:

```bash
make testnet-preflight            # readiness + costs, spends nothing
make network-state NETWORK=test NETUID=1
```

### Cost of the full Vanta topology

1 validator + 4 miners = 5 hotkeys × 0.0005 τ = **0.0025 τ**, or **~0.054 τ** with fee
headroom as the preflight reports it. Registering a *dedicated* subnet instead costs an
additional **1.0 τ** lock.

---

## Blocked: no funded testnet coldkey

Deployment stops here, and this is the only thing stopping it.

* `~/.bittensor/wallets` **does not exist** on this machine — there is no coldkey, no
  hotkey, and no testnet TAO.
* **There is no faucet.** `btcli` v11.1.0 has no `faucet` command, and the SDK's own error
  text is explicit:

  > `FaucetDisabled`: The `faucet` extrinsic was called on a runtime built without the
  > pow-faucet feature, i.e. any real network. The faucet only works on local test chains
  > compiled with that feature; **use a funded wallet or testnet TAO instead**.

So testnet TAO cannot be obtained programmatically. It requires a human action: a request
in the Bittensor Discord testnet faucet channel, or a transfer from an already-funded
testnet coldkey.

Creating the coldkey is also deliberately left to the operator: it generates a mnemonic
that only the wallet owner should ever see, and this repository never handles key material.

---

## Exact remaining steps

### 1. Create the wallet (operator does this; writes a mnemonic — back it up)

```bash
btcli wallet new-coldkey --wallet vanta
btcli wallet new-hotkey  --wallet vanta -H validator
btcli wallet new-hotkey  --wallet vanta -H miner0
btcli wallet new-hotkey  --wallet vanta -H miner1
btcli wallet new-hotkey  --wallet vanta -H miner2
btcli wallet new-hotkey  --wallet vanta -H miner3
```

### 2. Fund the coldkey with ~0.054 testnet TAO

Either request it in the Bittensor Discord testnet faucet channel, or transfer from a
funded testnet coldkey:

```bash
btcli wallet transfer --wallet <funded> --network test \
    --dest <vanta coldkey ss58> --amount 0.06
```

Confirm it arrived:

```bash
make testnet-preflight        # prints READY when the wallet, hotkeys and funds all exist
```

### 3. Register and publish endpoints

`--announce-ip` must be an address validators can actually reach; **the chain rejects
loopback** (verified on localnet in Phase 5).

```bash
python scripts/testnet_register.py --network test --netuid 1 --miners 4 \
    --wallet-name vanta --announce-ip <your public ip> --dry-run   # preview first
python scripts/testnet_register.py --network test --netuid 1 --miners 4 \
    --wallet-name vanta --announce-ip <your public ip>
```

### 4. Start the neurons

One process per miner (ports 8091–8094 must be reachable at the announced IP):

```bash
python scripts/run_miner.py --network test --netuid 1 --wallet-name vanta \
    --wallet-hotkey miner0 --engine persistence     --port 8091 --announce-ip <ip>
python scripts/run_miner.py --network test --netuid 1 --wallet-name vanta \
    --wallet-hotkey miner1 --engine mean-reversion  --port 8092 --announce-ip <ip>
python scripts/run_miner.py --network test --netuid 1 --wallet-name vanta \
    --wallet-hotkey miner2 --engine momentum        --port 8093 --announce-ip <ip>
python scripts/run_miner.py --network test --netuid 1 --wallet-name vanta \
    --wallet-hotkey miner3 --engine ml              --port 8094 --announce-ip <ip>
```

Then the validator:

```bash
python scripts/run_validator.py --network test --netuid 1 \
    --wallet-name vanta --wallet-hotkey validator
```

### 5. Verify

```bash
make network-state NETWORK=test NETUID=1
```

---

## Operational notes for whoever finishes this

These are real constraints observed on chain, not guesses.

* **netuid 1 on testnet is a shared subnet** — 256 neurons, 90 of them publishing
  endpoints belonging to other projects. A Vanta validator there will query those
  endpoints, get non-Vanta responses, and reject them at the collector (correct
  behaviour, but noisy and wasteful). For a clean demonstration, register a **dedicated
  subnet** (1.0 τ lock) with `btcli tx register-subnet` and use its netuid instead.
* **Commit-reveal is enabled**, so `SetWeights` takes the timelocked path: the plaintext
  `Weights` map stays empty until the chain auto-reveals at the drand round. The
  `TimelockedWeightsCommitted` event is the submission evidence, exactly as observed on
  localnet in Phase 5.
* **Weights rate limit is 100 blocks (~20 minutes)**. The validator's
  `--weight-interval` should be at least that; the SDK preflights the limit and reports
  how many blocks to wait.
* **Validator permit**: setting non-self weights requires a validator permit, which is
  earned by stake at epoch boundaries (tempo 99). A freshly registered, unstaked
  validator may be refused. Stake the validator hotkey and wait an epoch.
* **The MEV shield should work here.** `BurnedRegister` is MEV-shield-required, and the
  shield's 8-block era is ~96 seconds at 12s blocks — ample. The localnet escape hatch in
  `scripts/localnet_proof.py` was only needed because 0.25s fast blocks made that era ~2
  seconds. `testnet_register.py` therefore uses the normal intent path.
* **btcli v11.1.0 has a cosmetic crash on exit** in this environment
  (`typer._click.exceptions has no attribute 'Exit'`). Commands run and print their
  output correctly, but the process exits with a traceback and an unreliable exit code —
  do not gate scripts on `btcli`'s exit status.

---

## What *is* proven end-to-end

Phase 5 proved the identical code path against a **real subtensor chain** (a local node,
not a mock): registration, on-chain endpoint publication, metagraph discovery, signed HTTP
forecast requests, resolution, Vanta scoring, reputation, UID-aligned weights, and an
accepted `set_weights` extrinsic. See `docs/LOCALNET_EVIDENCE.md`.

The only thing the public testnet adds over that is a different chain endpoint and real
registration economics. No Vanta code differs between the two.
