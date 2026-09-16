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

Same payload: paper account snapshot, then Demo overlay when hub is up (`exec/hub_balance.py`). Typical keys: `start_balance`, `cash`, `realized_pnl`, `open_positions_notional`, `total_unrealized_pnl`, `equity`, `equity_mtm`, `currency`. Overlay may add Demo equity fields; on hub failure `hub_overlay_error` is set and paper values stay.

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

`{ "fills": [ ... ], "count": N, "source": "hub_demo" }` (or paper).

## `GET /history?limit=40`

`{ "trades": [ ... ], "count": N }` closed trades for the dashboard history/chart.

## `GET /api/chart/data?symbol=BTC/USDT:USDT&timeframe=15m&limit=400`

Chart payload from public OHLCV (`api/chart_data.py`): candles, RSI, markers. On failure: `{ "status": "error", "candles": [], "error": "..." }`.

## `GET /` · `GET /chart` · `GET /ui/live`

HTML dashboard, overlay chart page, live fragment. There is **no** `POST /scan/once` (scan can exceed HTTP timeouts). Run `python scripts/run_signal_loop.py --once` or `--poll`.
