# Research graveyard

Tried, measured, or considered — then **not** taken as the S2 product. This desk stays an Agentic Trading loop on **Bitget UTA Demo** (`hub_demo`). Not live mainnet.

## Signal / risk (this desk)

| Idea | What happened | Keep instead |
|------|----------------|--------------|
| Timeframe blocker on `15m` | The only TF. Ban + 7d cooldown shut the book (paper PnL ≈ $0 over ~46 trades). | `TF_BLOCKER_ENABLED=0`. Pair blocker stays. |
| Copy v1 `max_open_positions=60` | Bitget Demo + $500 notionals do not need a 60-slot book. | `MAX_POSITIONS=15` |
| `BTC_REGIME_TF=4h` because a live DB row said 4h | User standard is **1h**; 4h disagreed with `regime.py`. | `BTC_REGIME_TF=1h` |
| `BTC_EMA50_FILTER_ENABLED=1` | v1 had EMA50 off. Extra hard ban widens dead zones. | EMA50 off; log `btc_filter` reasons |
| Treat `PAPER_FALLBACK` PnL as Demo equity | Paper-live fills names missing on Demo. That cash is not UTA Demo. | Default `PAPER_FALLBACK=0`. Canonical log is Demo + paper-shadow of Demo only. |
| Ban `LEVEL_CROSS_*` / one-sided book | Both sides and all four types stay in `.env.example`. | Measure skips in `data/decisions.jsonl` before cutting types |

## Architecture we will not add

| Idea | Why it is in the graveyard |
|------|----------------------------|
| Research-only desk (NightDesk-style factory / overfit court as the product) | Track 2 wants **event → decision → execution**. This repo already has that on Demo UTA. Research notes belong here, not as a second product. |
| Optic-style multi-agent debate (bull/bear/judge as the decision path) | Extra LLM round-trips, no Demo fill. `agent.decide` is rules or one LLM call with rules fallback. |
| On-chain attestation / Ed25519 / TEE / 0G DecisionLogger | Out of scope for Bitget Demo UTA. We hash canonical JSON locally (`desk/decision_log.py`); `scripts/verify_decision_log.py` recomputes it. |
| Context Sync MCP | Not wired in this workspace. Do not invent tool headers. |
| Live mainnet | `BITGET_ALLOW_LIVE=0`. Hackathon evidence is Demo + paper shadow. |

## How to add a new tombstone

One row: idea, symptom (what the system actually did), replacement. Do not rewrite history as a confident cause if you only have a symptom.
