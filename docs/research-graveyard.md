# Research graveyard

Tried, measured, or considered — then **not** taken as the S2 product. This desk stays an Agentic Trading loop on **Bitget UTA Demo** (`hub_demo`). Not live mainnet.

## Signal / risk (this desk)

| Idea | What happened | Keep instead |
|------|----------------|--------------|
| Timeframe blocker on `15m` | Ban + 7d cooldown shut the 15m-only book. | `TF_BLOCKER_ENABLED=0`. Desk now scans `15m,1h,4h`. Pair blocker stays. |
| Copy v1 `max_open_positions=60` | Bitget Demo + $500 notionals do not need a 60-slot book. | `MAX_POSITIONS=15` + `MAX_SAME_DIRECTION_POSITIONS=4` |
| `BTC_REGIME_TF=1h` while v1 DB is 4h | 1h BTC below EMA200 (bearish→shorts); 4h above (bullish). Split books. | `BTC_REGIME_TF=4h` |
| `RSI_LONG_MAX=30` (v1) | Signal-bar RSI on bullish div is almost always >30 (min ~30.6 over 189 longs). Zone killed longs. | `RSI_LONG_MAX=0` |
| `MAX_DAILY_LOSS_USD=50` | Halted the book overnight on a -$49 day. | `150` |
| Allow `LEVEL_CROSS_UP` | User 2026-09-16 dropped it from `ALLOWED_TYPES`. | `BULLISH_DIV,BEARISH_DIV,LEVEL_CROSS_DOWN` |
| `BTC_EMA50_FILTER_ENABLED=1` | Extra hard ban widens dead zones. | EMA50 off; log `btc_filter` reasons |
| Treat `PAPER_FALLBACK` PnL as Demo equity | Paper-live fills names missing on Demo. That cash is not UTA Demo. | Default `PAPER_FALLBACK=0`. Canonical log is Demo + paper-shadow of Demo only. |

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
