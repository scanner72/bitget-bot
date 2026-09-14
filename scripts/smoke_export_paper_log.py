"""Smoke: export_paper_log maps native paper fills to S2 checklist columns.

Offline; no network, no API keys. Uses the committed sample fixture and a
temp-dir native jsonl that matches exec/paper.py.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCRIPT = ROOT / "scripts" / "export_paper_log.py"
FIXTURE = ROOT / "docs" / "evidence" / "fixtures" / "paper_fills.sample.jsonl"
DECISIONS = ROOT / "docs" / "evidence" / "fixtures" / "decisions.sample.jsonl"


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _load_mod():
    spec = importlib.util.spec_from_file_location("export_paper_log", SCRIPT)
    _assert(spec is not None and spec.loader is not None, "cannot load export_paper_log")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    mod = _load_mod()
    required = list(mod.CHECKLIST_COLUMNS)

    with tempfile.TemporaryDirectory(prefix="bitget_export_log_") as tmp:
        tmp_path = Path(tmp)
        out_csv = tmp_path / "paper_trading_log.csv"
        out_jsonl = tmp_path / "paper_trading_log.jsonl"

        rows = mod.export_log(
            fills_path=FIXTURE,
            decisions_path=DECISIONS,
            out_csv=out_csv,
            out_jsonl=out_jsonl,
            start_balance=10000.0,
            label="SIMULATED_DEMO",
        )
        print(f"fixture rows={len(rows)} csv={out_csv}")
        _assert(len(rows) == 7, f"expected 7 sample fills, got {len(rows)}")
        csv_rows = _read_csv(out_csv)
        _assert(len(csv_rows) == 7, csv_rows)
        for col in required:
            _assert(col in csv_rows[0], f"missing checklist column {col}: {csv_rows[0].keys()}")

        btc_open = csv_rows[0]
        _assert(btc_open["trading_pair"] == "BTC/USDT:USDT", btc_open)
        _assert(btc_open["direction"] == "long", btc_open)
        _assert(btc_open["event"] == "open", btc_open)
        _assert(btc_open["account_balance_change"] in {"0", "0.0"}, btc_open)
        _assert(btc_open["mode"] == "hub_demo", btc_open)
        _assert(btc_open["status"] == "filled", btc_open)
        _assert(btc_open["label"] == "SIMULATED_DEMO", btc_open)
        _assert(btc_open["signal_type"] == "BULLISH_DIV", btc_open)

        btc_close = csv_rows[1]
        _assert(btc_close["event"] == "close", btc_close)
        _assert(float(btc_close["account_balance_change"]) == 5.0, btc_close)
        _assert(float(btc_close["equity_after"]) == 10005.0, btc_close)
        _assert(btc_close["exit_status"] == "tp1_trail", btc_close)

        eth_close = csv_rows[3]
        _assert(eth_close["direction"] == "short", eth_close)
        _assert(float(eth_close["account_balance_change"]) == 2.0, eth_close)
        _assert(float(eth_close["equity_after"]) == 10007.0, eth_close)

        sol_open = csv_rows[4]
        _assert(sol_open["mode"] == "paper_live", sol_open)
        sol_close = csv_rows[5]
        _assert(float(sol_close["account_balance_change"]) == -3.0, sol_close)
        _assert(float(sol_close["equity_after"]) == 10004.0, sol_close)

        doge = csv_rows[6]
        _assert(doge["event"] == "open", doge)
        _assert(float(doge["equity_after"]) == 10004.0, doge)
        _assert(float(doge["cash_after"]) == 9924.0, doge)

        jsonl_rows = [
            json.loads(line)
            for line in out_jsonl.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        _assert(len(jsonl_rows) == 7, jsonl_rows)
        dumped = json.dumps(jsonl_rows).lower()
        for bad in ("api_key", "secret_key", "passphrase", "bitget_secret"):
            _assert(bad not in dumped, f"secret-looking key leaked: {bad}")

        # Native paper.py-shaped fills in a temp data dir (local-run path).
        local_fills = tmp_path / "paper_fills.jsonl"
        local_fills.write_text(
            json.dumps(
                {
                    "ts": "2026-09-08T16:09:55.874747+00:00",
                    "fill_id": "fill_790d9f5df797",
                    "position_id": "pos_abf778d678d2",
                    "event": "open",
                    "symbol": "BTC/USDT:USDT",
                    "side": "long",
                    "size_usd": 50.0,
                    "qty": 50.0 / 65000.0,
                    "price": 65000.0,
                    "realized_pnl": 0.0,
                    "meta": {"type": "BULLISH_DIV", "action": "ENTER"},
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
            + json.dumps(
                {
                    "ts": "2026-09-08T17:00:00+00:00",
                    "fill_id": "fill_close_local",
                    "position_id": "pos_abf778d678d2",
                    "event": "close",
                    "symbol": "BTC/USDT:USDT",
                    "side": "long",
                    "size_usd": 50.0,
                    "qty": 50.0 / 65000.0,
                    "price": 66000.0,
                    "entry_price": 65000.0,
                    "realized_pnl": 50.0 * ((66000.0 / 65000.0) - 1.0),
                    "meta": {"exit_status": "tp2"},
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        local_csv = tmp_path / "local.csv"
        local_jsonl = tmp_path / "local.jsonl"
        rc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--fills",
                str(local_fills),
                "--out-csv",
                str(local_csv),
                "--out-jsonl",
                str(local_jsonl),
                "--start-balance",
                "10000",
                "--label",
                "DEMO",
            ],
            check=False,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        print(rc.stdout)
        _assert(rc.returncode == 0, rc.stderr or rc.stdout)
        local_rows = _read_csv(local_csv)
        _assert(len(local_rows) == 2, local_rows)
        expected_pnl = 50.0 * ((66000.0 / 65000.0) - 1.0)
        _assert(abs(float(local_rows[1]["account_balance_change"]) - expected_pnl) < 1e-9, local_rows[1])
        _assert(local_rows[1]["label"] == "DEMO", local_rows[1])
        _assert(local_rows[0]["mode"] == "paper_shadow", local_rows[0])

        # GET /fills JSON wrapper (docs/demo_artifacts/fills.json shape).
        wrapped = tmp_path / "fills.json"
        wrapped.write_text(
            json.dumps(
                {
                    "fills": [
                        {
                            "ts": "2026-09-08T16:09:55.874747+00:00",
                            "fill_id": "fill_790d9f5df797",
                            "position_id": "pos_abf778d678d2",
                            "event": "open",
                            "symbol": "BTC/USDT:USDT",
                            "side": "long",
                            "size_usd": 50.0,
                            "qty": 0.0007692307692307692,
                            "price": 65000.0,
                            "realized_pnl": 0.0,
                            "meta": {"type": "BULLISH_DIV"},
                        }
                    ],
                    "count": 1,
                }
            ),
            encoding="utf-8",
        )
        wrap_rows = mod.build_rows(
            mod._load_json_records(wrapped),
            start_balance=10000.0,
            label="DEMO",
        )
        _assert(len(wrap_rows) == 1, wrap_rows)
        _assert(wrap_rows[0]["trading_pair"] == "BTC/USDT:USDT", wrap_rows[0])

        # CLI --from-sample (judges, no data/).
        sample_csv = tmp_path / "from_sample.csv"
        sample_jsonl = tmp_path / "from_sample.jsonl"
        rc2 = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--from-sample",
                "--out-csv",
                str(sample_csv),
                "--out-jsonl",
                str(sample_jsonl),
            ],
            check=False,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        print(rc2.stdout)
        _assert(rc2.returncode == 0, rc2.stderr or rc2.stdout)
        from_sample = _read_csv(sample_csv)
        _assert(len(from_sample) == 7, from_sample)
        _assert(from_sample[0]["label"] == "SIMULATED_DEMO", from_sample[0])

        rc_live = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--from-sample",
                "--label",
                "LIVE",
                "--out-csv",
                str(tmp_path / "nope.csv"),
                "--out-jsonl",
                str(tmp_path / "nope.jsonl"),
            ],
            check=False,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        _assert(rc_live.returncode == 2, rc_live.stdout + rc_live.stderr)

    print("smoke_export_paper_log OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
