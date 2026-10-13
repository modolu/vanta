# Vanta — 48-Hour Hackathon Progress

## Deadline

**2026-10-15 23:59 UTC+1**

Current time at kickoff: **2026-10-13 13:38 UTC+1**.
Build window: 48 hours. Final buffer after the build window is reserved for emergency fixes and submission.

## Approved scope

### Must-have

- Verify/recover public Bittensor testnet subnet **netuid 564**.
- Confirm validator state, balance, registration burn, permit, and metagraph topology.
- Register and run **at least four miners** (`miner0`–`miner3`) when economics are acceptable.
- Complete at least one real **15-minute** public testnet lifecycle:
  task → signed miner forecasts → persistence → market resolution → Vanta Score → reputation → weights → Bittensor submission.
- Capture durable testnet evidence: netuid, public hotkeys/UIDs, task ID, forecasts, resolution, scores, reputation, weights, block/extrinsic.
- Build a minimal judge-facing **Vanta Terminal**.
- Dashboard must show ETH outlook, probability, expected return, consensus, active miners, and subnet/testnet status.
- Leaderboard must show miner score, reputation/calibration, weight, and forecast count where supported by real data.
- Every data-driven UI must have loading, empty, and error states.
- Deploy the judge-facing frontend to **Vercel**.
- Update README/testnet docs to match verified live state.
- Produce submission copy, screenshots/evidence, demo flow, and final release checks.

### Nice-to-have

- Miner detail screen.
- Small historical performance/calibration visualization.
- Live chain-state refresh in the UI.
- Public read-only API documentation.

### Cut for this hackathon

- Trading or order execution.
- Additional assets/horizons beyond ETH/USD 15m.
- New miner strategies or strategy tuning.
- PostgreSQL migration.
- Redis.
- Multiple independent validators.
- Sophisticated collusion detection.
- Cross-venue median/TWAP oracle system.
- User authentication/accounts.
- Mobile app.
- Billing or institutional API features.

## Locked decisions

- `ARCHITECTURE.md` and `vanta_product_brief.md` are the product/source-of-truth documents.
- Existing mechanism/scoring decisions remain frozen unless explicitly approved.
- Runtime remains **Python 3.12 + bittensor 11.1.0**.
- Miner/validator networking remains current v11 **signed HTTP** via FastAPI/httpx + `bittensor.http_auth`; do not regress to removed Axon/Dendrite/Synapse APIs.
- Validator persistence remains **SQLite** for the hackathon.
- Vanta Terminal is a **read-only presentation layer**, not the subnet runtime.
- Frontend direction: **Next.js + TypeScript**, deployed to Vercel.
- Real Bittensor proof comes before UI polish.
- Do not claim directional alpha from the baseline miners.
- Commit/reveal remains enabled on testnet; do not disable it just to make evidence easier.

## Task plan

1. **DONE — Re-anchor repo + testnet**
   - Done when: repo is clean/green; current testnet subnet 564, validator, balance, burn, permit, and chain state are verified; sprint docs exist; product brief is committed.
   - Estimate: 45–60 min.

2. **IN PROGRESS — Complete public testnet topology**
   - Done when: validator + >=4 miners are registered and visible in the metagraph; miner endpoints are published and reachable by the validator.
   - Estimate: 60–90 min.

3. **TODO — Run public Vanta cycle** — MILESTONE 1
   - Done when: one real 15m task receives signed forecasts, resolves, scores, updates reputation, and submits weights successfully on public testnet; chain evidence captured.
   - Estimate: 60–90 min active work plus unavoidable horizon/chain waits.

4. **TODO — Freeze demo/evidence contract**
   - Done when: verified testnet/state data is exposed through one stable typed presentation schema for the frontend; no duplicated drifting definitions.
   - Estimate: 45 min.

5. **TODO — Vanta Terminal vertical slice**
   - Done when: Next.js app shows ETH outlook, consensus, and subnet status end-to-end through its data route, with loading/empty/error states.
   - Estimate: 60–90 min.

6. **TODO — Leaderboard vertical slice** — MILESTONE 2
   - Done when: miners render with score/reputation/calibration/weight/forecast count where supported, and all states are demo-safe.
   - Estimate: 60–90 min.

7. **TODO — Miner detail + mechanism explanation**
   - Done when: one miner detail view explains score breakdown/recent performance clearly; if time slips, this is the first feature to cut.
   - Estimate: 60 min.

8. **TODO — Vercel deployment** — MILESTONE 3
   - Done when: production URL works in a fresh browser, desktop/mobile layout is usable, no secrets are exposed, and no blank/raw-error screens exist.
   - Estimate: 60–90 min.

9. **TODO — Repository/submission hardening**
   - Done when: README/testnet docs reflect netuid 564 and current evidence; stale blockers removed; setup/run/demo steps verified.
   - Estimate: 60–75 min.

10. **TODO — Judging package**
    - Done when: submission copy maps Vanta cleanly to the seven HackQuest judging criteria; evidence/screenshots selected.
    - Estimate: 45–60 min.

11. **TODO — Demo rehearsal + video material** — MILESTONE 4
    - Done when: deterministic <2 minute demo path and script are ready without relying on fragile live steps.
    - Estimate: 60–90 min.

12. **TODO — Final regression/release**
    - Done when: relevant tests/lint/build pass, Vercel links work, git is clean, docs are current, and final commit/release state is submission-ready.
    - Estimate: 60–90 min.

## Timeline

- **Hour 0–6:** Tasks 1–3. Eliminate public-testnet risk first.
- **Hour 6–16:** Tasks 4–6. Build first judge-facing terminal and leaderboard.
- **Hour 16–24:** Tasks 7–8. Miner detail only if core is stable, then Vercel deployment.
- **Hour 24–34:** Tasks 9–10. Repo/evidence/submission hardening.
- **Hour 34–42:** Task 11 plus approved nice-to-haves only if ahead.
- **Hour 42–48:** Feature freeze. Task 12, fixes, deployment verification, README/submission, video.
- **No new features after Hour 42.**

## Decisions and why

- **Finish real testnet proof before UI:** the subnet mechanism is the core judging story; UI without chain proof is weaker.
- **Keep SQLite:** migration risk adds little judging value.
- **Use Next.js + TypeScript on Vercel:** simplest reliable judge-facing deployment target while keeping Python subnet runtime untouched.
- **Keep frontend read-only:** avoids introducing auth, writes, wallet handling, and operational risk.
- **Use verified/real Vanta state in the demo contract:** avoid a fake dashboard; if live transport is unreliable, use a clearly labelled verified snapshot generated from real testnet evidence.
- **No alpha claim:** historical baselines are evidence that the scoring mechanism separates calibration/return quality, not evidence of predictive edge.

## Later

- Cross-venue median/TWAP resolution.
- PostgreSQL store.
- Multiple validators/operators.
- Additional assets and horizons.
- Better miner strategies / external independent miners.
- Formal network-confidence equation.
- Miner forecast commit/reveal.
- Advanced collusion/similarity analysis.
- Institutional/API monetization features.

## Known issues / workarounds

- **README is stale:** it still describes public testnet as undeployed. Live state was re-verified on 2026-10-13; fix the README after the public cycle/evidence is complete so it reflects final facts.
- **Dedicated public testnet subnet 564:** verified live at block ~8,212,761; registration is allowed; tempo 360; commit-reveal enabled; weights rate limit 100 blocks.
- **Validator:** UID 0, validator permit **true**, currently inactive because no serving endpoint/round activity yet.
- **Balance:** free testnet balance verified at **τ3.974888753**.
- **Miner registration burn:** verified at the minimum **τ0.000500000 per hotkey**. The previous economic blocker is gone; registration is now cheap enough to proceed.
- **Current topology:** 1 neuron (validator), 0 miner neurons, 0 serving endpoints. `make testnet-preflight NETWORK=test NETUID=564` reports READY.
- **btcli cosmetic Typer bug:** some successful commands may print a useful result then throw an `AttributeError`/`Abort`; verify the printed chain result rather than trusting exit code alone.
- **Commit/reveal:** accepted weight commits may not appear immediately as plaintext weights; distinguish commit acceptance, reveal completion, and visible weights in evidence.
- **Claude Code headless session:** first kickoff attempt did not complete cleanly in the remote terminal; do not retry blindly. Use direct setup edits for Task 1 and re-test a minimal headless command before delegating implementation work.

## Time check

- Kickoff: **2026-10-13 13:38 UTC+1**.
- Deadline: **2026-10-15 23:59 UTC+1**.
- Status: **ON TRACK**.
- Current critical path: register miner0–miner3, publish reachable endpoints, then complete a real 15-minute cycle before frontend work.
