# Evidence — paper / Demo trading log

Bitget S2 **Trading Agent** checklist asks for a public live or paper trading log with:

`timestamp`, `trading pair`, `direction`, `price`, `quantity`, `account balance change`

This folder is that log. **It is not live mainnet.**

| What you are looking at | Meaning |
|-------------------------|---------|
| Bitget **UTA Demo** (`hub_demo`, `paptrading`) | Exchange fills on the Demo book |
| **Paper shadow** | Local book used for ATR TP1 / BE / trail next to Demo |
| **Paper-live** (`PAPER_FALLBACK`) | Local fill when a pair is missing on Demo. **Do not add that PnL to Demo equity** |

`BITGET_ALLOW_LIVE=0`. Runtime `data/*.jsonl` is gitignored and is never committed with keys.

## Public files (judges)

| File | Role |
|------|------|
| [`paper_trading_log.csv`](paper_trading_log.csv) | Canonical checklist CSV: **Bitget UTA Demo** fills only (`hub_demo` + paper-shadow closes of those Demo positions). Not paper-live, not Divergent V1. |
| [`paper_trading_log.jsonl`](paper_trading_log.jsonl) | Same rows, one JSON object per line |
| [`paper_trading_log.sample.csv`](paper_trading_log.sample.csv) | Sanitized **SIMULATED_DEMO** snapshot, always labeled |
| [`fixtures/paper_fills.desk.jsonl`](fixtures/paper_fills.desk.jsonl) | Native fills from this desk (source for the canonical log) |
| [`fixtures/paper_fills.sample.jsonl`](fixtures/paper_fills.sample.jsonl) | Tiny offline fixture for `--from-sample` |

Dashboard dumps (not the checklist log): [`docs/demo_artifacts/`](../demo_artifacts/).

## Columns

Checklist fields first, then desk extras:

| Column | Source |
|--------|--------|
| `timestamp` | Fill `ts` (ISO-8601 UTC) |
| `trading_pair` | ccxt swap symbol, e.g. `BTC/USDT:USDT` |
| `direction` | `long` or `short` |
| `price` | Fill price |
| `quantity` | Fill `qty` (base coins) |
| `account_balance_change` | Reconstructed **Demo-venue** equity delta (`0` on open, realized PnL on close). Same cash model as `exec/account.py`. This is **not** a Bitget UTA wallet snapshot (needs Demo API keys). |
| `status` | `filled` |
| `mode` | `hub_demo` · `paper_shadow` · `paper_live` |
| `event` | `open` / `close` |
| `size_usd` | Notional locked |
| `realized_pnl` | Close PnL (0 on open) |
| `cash_change` / `cash_after` / `equity_after` | Reconstructed from `PAPER_START_BALANCE_USD` (default `10000`) |
| `label` | `DEMO` (this desk) or `SIMULATED_DEMO` (`--from-sample`) |
| `signal_type` | From fill `meta.type` or joined `decisions.jsonl` |

PnL on a close is the linear paper formula: long `size_usd * (exit/entry - 1)`; short inverted (`exec/paper.py`).

## Regenerate

This desk’s UTA Demo fills (no `data/`, no keys, **not** paper-live, **not** Divergent V1):

```bash
python scripts/export_paper_log.py --from-desk
# keeps positions that hit Bitget UTA Demo (hub_demo)
# plus local paper-shadow closes of those same positions
# drops PAPER_FALLBACK / paper_live
# writes docs/evidence/paper_trading_log.csv and .jsonl
```

Tiny offline sample (does **not** replace the canonical desk log unless you pass `--out-csv`):

```bash
python scripts/export_paper_log.py --from-sample --write-sample
```

From a real local desk run (`data/` is gitignored):

```bash
python scripts/export_paper_log.py
# reads data/paper_fills.jsonl + data/decisions.jsonl when present
# otherwise falls back to fixtures/paper_fills.desk.jsonl
```

Optional: `--fills path` (JSONL or `{"fills":[...]}` as in `GET /fills`), `--start-balance 10000`.

The exporter refuses `--label LIVE` / `MAINNET`. Do not commit `.env` or `data/`. Do not merge Divergent V1 paper trades into this log. Do not add `paper_live` PnL to Demo equity. To include fallback fills: `--from-desk --include-paper-live`.
