# Bitget Hackathon S2 — form copy

Official form: <https://forms.gle/GyWZCMCPocgJdJon6>  
Deadline: **21 Sep 2026, 23:59 UTC+8** (**18:59 UTC+3**).

Private identity fields (Bitget UID, email, Telegram) must be entered by the team lead and are intentionally not stored in Git.

## Recommended selections

- Participant type: **Developer**
- Competition sub-theme: **Agentic Trading**
- Project name / team name: **Divergent Agent Desk**
- S1 participation: answer truthfully. If **Yes**, paste the additions block below.

## One-line Project Summary (≤140 characters)

Autonomous multi-TF RSI divergence agent with LLM decisions, deterministic risk controls, and verifiable Bitget UTA Demo execution.

Length: 131 characters.

## Project Description

### Part 1 · Thesis

Crypto and tokenized traditional assets trade around the clock, while discretionary monitoring does not scale across instruments and timeframes. Our hypothesis is that a compact autonomous loop can identify confirmed RSI-momentum divergence and selected level-cross events on 15m, 1h, and 4h; let an LLM apply an explicit decision policy; and execute safely on Bitget UTA Demo.

The agent does not ask the model to invent market data or bypass controls. Public Bitget WebSocket/REST candles feed deterministic signal detection. The decision layer returns ENTER or SKIP with a rationale and falls back to rules if the model fails. Every entry then passes risk-to-stop sizing, a BTC regime filter, pair performance blocking, a four-position same-direction correlation cap, a $150 daily kill, price-scale validation, and Demo-catalog validation. Exchange SL and TP2 are placed with the order; TP1, breakeven, and trailing logic are maintained by the local shadow and reconciled against Bitget.

### Part 2 · Target user and product value

The target user is a crypto or cross-asset trader who wants an inspectable autonomous desk rather than an opaque signal bot. The desk covers both crypto perps and Bitget rToken/RWA instruments, uses instrument-aware ATR for stock-style products, and exposes decisions, fills, positions, risk state, and equity through a FastAPI dashboard.

The product value is operational verifiability: users can see why a trade was accepted or rejected, compare local strategy state with authoritative Bitget fills/equity, reproduce the evidence exporter, and verify the SHA-256 decision chain. Live mainnet is deliberately disabled for this submission.

### Part 3 — Validation data and key metrics

**Observed Bitget UTA Demo, 9–18 Sep 2026:**

- 148 public strategy-ledger records: 75 opens and 73 closes across 35 instruments.
- Current Demo equity at capture: 9,880.54 USDT from a 10,000 USDT anchor; observed return **−1.195%**.
- Recent captured exchange window: 100 Bitget fills; close `exec_pnl` **+41.64 USDT** and fees **42.57 USDT**.
- Demo-linked paper-shadow diagnostics: 30.14% win rate, 1.228 profit factor, 0.761% reconstructed max drawdown, 1.515 daily Sharpe and 2.430 daily Sortino (annualized ×365).
- Turnover proxy: 28,375.18 USDT one-way open notional (2.837× start AUM); 55,750.35 USDT two-way logged notional.
- Signed entry slippage: mean 92.60 bps, median 57.38 bps across 45 measurable opens.
- Funding is not available in the captured fills payload and is excluded.

All figures are labeled observed. Demo equity and exchange fills are authoritative for money; paper-shadow statistics are strategy diagnostics and may differ. The sample is short, so Sharpe/Sortino are exploratory, not a stable expected-performance or out-of-sample claim. The still-negative Demo equity path is reported without cherry-picking and motivated concrete controls: symbol/quantity fill matching, Demo price-scale rejection, adaptive leverage, and instrument-specific ATR.

### Part 4 — Progress and proof of effective use

The repository is public and runnable with Docker Compose. The local desk is continuously connected to Bitget UTA Demo, scans the Demo catalog on 15m/1h/4h, and exposes live `/health`, `/positions`, `/fills`, `/history`, `/decisions`, and `/equity` endpoints. The captured evidence contains 75 observed opens and approximately 55.75k USDT of two-way logged notional. In the latest artifact, 100 of 100 recent decisions used the LLM path with deterministic fallback available.

Observed activation is the running autonomous desk and its trade/fill history. Observed AUM is 9,880.54 USDT Demo equity at capture. External-user retention is not claimed; the current validation is a single-team autonomous deployment. Incremental fee evidence is 42.57 USDT across the captured recent exchange fills. The next validation target is a longer unchanged-policy window with exchange-native funding and complete fill pagination.

### Part 5 · Our take on AI Trading

An LLM should not be treated as a source of magical alpha or as a replacement for exchange truth. Its useful role is to apply a transparent decision contract, produce human-readable rationale, and operate continuously across a wide event stream. Deterministic code must retain authority over sizing, allowed instruments, daily loss, correlation, stop placement, price sanity, and reconciliation.

This separation makes the system safer and easier to audit: model failures fall back to rules; every decision records its context and policy manifest; and monetary reporting always prioritizes Bitget equity and `exec_pnl` over local estimates. The observed loss is itself useful validation of this architecture because it exposes where AI reasoning ends and execution/risk engineering must begin.

## Submission Material Links

Use one labeled link per line:

```text
Project · Public GitHub: https://github.com/scanner72/bitget-bot
Run records · Agentic Trading log: https://github.com/scanner72/bitget-bot/blob/main/docs/evidence/paper_trading_log.csv
Validation · Metrics and limitations: https://github.com/scanner72/bitget-bot/blob/main/docs/evidence/s2_validation.md
Validation data · Machine-readable metrics: https://github.com/scanner72/bitget-bot/blob/main/docs/evidence/s2_validation.json
Demo evidence · Bitget fills snapshot: https://github.com/scanner72/bitget-bot/blob/main/docs/demo_artifacts/fills.json
Demo evidence · Bitget equity snapshot: https://github.com/scanner72/bitget-bot/blob/main/docs/demo_artifacts/equity.json
Decision integrity · Hashed fixture: https://github.com/scanner72/bitget-bot/blob/main/docs/evidence/fixtures/decisions.hashed.jsonl
Architecture · System design: https://github.com/scanner72/bitget-bot/blob/main/docs/architecture.md
```

Add the public video and X post as additional labeled lines if produced. Do not add placeholders to the submitted form.

## Material Additions Since S1 (only if the team participated in S1)

This S2 entry adds substantial functionality rather than a rename:

- native Bitget UTA Demo execution with exchange SL/TP2 and authoritative equity/fill views;
- multi-timeframe 15m/1h/4h WebSocket scanning;
- rToken/stock-aware 1h ATR without the crypto 2% floor;
- adaptive leverage capped at 20× based on stop distance;
- same-direction correlation guard and revised daily loss policy;
- Demo-catalog and pre/post-fill price-scale protection;
- symbol/quantity-aware fill reconciliation;
- LLM decision contract with rules fallback;
- tamper-evident SHA-256 decision chain with session, context, and policy manifest;
- reproducible public evidence and validation generators.
