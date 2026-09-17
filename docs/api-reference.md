# API

Base: `http://127.0.0.1:8080`. HTML on `/` and `/chart`; everything else JSON. Handlers in `api/app.py`.

## `GET /health`

```json
{
  "ok": true,
  "paper": true,
  "exec_mode": "hub_demo",
  "hub_demo": true,
  "bitget_demo": true,
  "hub_sync_exchange_sl": true,
  "paper_fallback": false,
  "agent_mode": "llm",
  "openai_model": "qwen/qwen3.6-27b"
}
```

`paper` is always true (shadow book). `paper_fallback` is true only when `PAPER_FALLBACK=1` **and** `exec_mode` is `hub_demo` (default off — Demo catalog only). `agent_mode` is `rules` or `llm`. `openai_model` is the Chat Completions model when `llm`, else `""`. No API key is returned.

## `GET /account` and `GET /equity`

Same payload: paper account snapshot, then Demo overlay when hub is up (`exec/hub_balance.py`). In `hub_demo`, the **top-level Demo values are the monetary source of truth**: `equity` / `demo_equity`, `pnl_vs_start`, `hub_available`, and `hub_unrealised_pnl`. The local mirror remains under `paper`; it is useful for bot accounting but may differ from Bitget.

If the hub request fails, `hub_overlay_error` is set and paper values remain. Do not present that fallback as confirmed exchange equity.

## `GET /positions`

Object, not a bare array (`exec/hub_view.py`):

```json
{
  "positions": [],
  "count": 0,
  "total_unrealized_pnl": 0,
  "stale_count": 0,
  "source": "hub_demo",
  "untracked_count": 0,
  "mtm_errors": []
}
```

`source` is `hub_demo`, `live`, or `paper`. Rows keep ccxt `symbol` plus `symbol_id` / `symbol_display`. Demo rows carry exchange entry/mark/PnL/`exchange_leverage`; paper-live rows are tagged as the fallback venue. Hub opens set `HUB_LEVERAGE` (default 20) via UTA `set-leverage` before the market order.

## `GET /decisions?limit=50`

`{ "decisions": [ ... ], "count": N }` — tail of `data/decisions.jsonl`. Rows include agent/risk fields plus, after the S2 hardening pass: `session_id`, `context`, `manifest`, `manifest_hash`, `prev_hash`, `hash` (SHA-256 of canonical JSON with `hash` omitted). Verify a fixture with `python scripts/verify_decision_log.py`.

## `GET /candidates?limit=50`

`{ "candidates": [ ... ], "count": N }` — tail of `data/candidates.jsonl`.

## `GET /fills?limit=50`

`{ "fills": [ ... ], "count": N, "source": "hub_demo" }` (or paper). With `source=hub_demo`, rows come from Bitget UTA and `exec_pnl` is the authoritative realized execution PnL. Fees are separate in `fee`.

## `GET /history?limit=40`

`{ "trades": [ ... ], "count": N }` closed trades reconstructed from local `data/paper_fills.jsonl`. This is **paper-shadow history**, used for bot exit status, SL/TP overlays and analysis. Its `realized_pnl` can differ from Bitget `exec_pnl` because of fill price, quantity, fees, delayed reconciliation, or an unmatched hub fill.

## PnL source precedence

For `EXEC_MODE=hub_demo`, use this order:

1. `/equity` — authoritative current Demo wallet/equity.
2. `/fills` with `source=hub_demo` — authoritative execution-level `exec_pnl` and fees.
3. `/history` — local paper-shadow reconstruction; never override exchange money with it.

The dashboard **Trade history** tab shows item 3. The Account card uses item 1.

## `GET /api/chart/data?symbol=BTC/USDT:USDT&timeframe=15m&limit=400`

Chart payload from public OHLCV (`api/chart_data.py`): candles, RSI, markers. On failure: `{ "status": "error", "candles": [], "error": "..." }`.

## `GET /` · `GET /chart` · `GET /ui/live`

HTML dashboard, overlay chart page, live fragment. There is **no** `POST /scan/once` (scan can exceed HTTP timeouts). Run `python scripts/run_signal_loop.py --once` or `--poll`.
