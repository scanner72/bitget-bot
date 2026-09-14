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
DESK_FILLS = ROOT / "docs" / "evidence" / "fixtures" / "paper_fills.desk.jsonl"
COMMITTED_CSV = ROOT / "docs" / "evidence" / "paper_trading_log.csv"


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

        rc_both = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--from-sample",
                "--from-desk",
                "--out-csv",
                str(tmp_path / "both.csv"),
                "--out-jsonl",
                str(tmp_path / "both.jsonl"),
            ],
            check=False,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        _assert(rc_both.returncode == 2, rc_both.stdout + rc_both.stderr)

        _assert(DESK_FILLS.exists(), f"missing {DESK_FILLS}")
        desk_native = [
            json.loads(line)
            for line in DESK_FILLS.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        _assert(len(desk_native) >= 50, f"desk fixture too small: {len(desk_native)}")
        for rec in desk_native:
            pid = str(rec.get("position_id") or "")
            fid = str(rec.get("fill_id") or "")
            _assert(not pid.startswith("div_v1_"), pid)
            _assert(not fid.startswith("div_v1_"), fid)
            blob = json.dumps(rec, ensure_ascii=False).lower()
            _assert("divergent_v1" not in blob, rec)
            _assert("divergent_paper_trades" not in blob, rec)

        for rec in desk_native:
            if str(rec.get("symbol") or "").startswith("BTC/"):
                px = float(rec.get("price") or 0)
                _assert(abs(px - 65000.0) > 1e-6, f"dummy smoke BTC price leaked: {rec}")

        desk_csv = tmp_path / "desk.csv"
        desk_jsonl = tmp_path / "desk.jsonl"
        rc_desk = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--from-desk",
                "--out-csv",
                str(desk_csv),
                "--out-jsonl",
                str(desk_jsonl),
                "--start-balance",
                "10000",
            ],
            check=False,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        print(rc_desk.stdout)
        _assert(rc_desk.returncode == 0, rc_desk.stderr or rc_desk.stdout)
        desk_rows = _read_csv(desk_csv)
        _assert(len(desk_rows) == len(desk_native), (len(desk_rows), len(desk_native)))
        _assert(all(r["label"] == "DEMO" for r in desk_rows), desk_rows[0])
        _assert(float(desk_rows[0]["equity_after"]) == 10000.0, desk_rows[0])
        modes = {r["mode"] for r in desk_rows}
        _assert(modes <= {"hub_demo", "paper_shadow", "paper_live"}, modes)
        _assert("hub_demo" in modes, modes)

        committed = _read_csv(COMMITTED_CSV)
        _assert(len(committed) == len(desk_rows), (len(committed), len(desk_rows)))
        _assert(
            all(not (r.get("position_id") or "").startswith("div_v1_") for r in committed),
            "committed log still contains Divergent V1 ids",
        )
        committed_ids = [r["fill_id"] for r in committed]
        desk_ids = [r["fill_id"] for r in desk_rows]
        _assert(committed_ids == desk_ids, (committed_ids[:3], desk_ids[:3]))
        _assert(
            not any(
                r["trading_pair"].startswith("BTC/") and abs(float(r["price"]) - 65000.0) < 1e-6
                for r in committed
            ),
            "committed log still has dummy BTC@65000 smoke fills",
        )

        fills, _dec, label, origin = mod.resolve_inputs(
            fills_path=None,
            decisions_path=None,
            from_sample=False,
            from_desk=False,
        )
        _assert(label == "DEMO", label)
        _assert(origin in {"local_data", "desk_fixture"}, origin)
        if origin == "desk_fixture":
            _assert(fills == DESK_FILLS, fills)

    print("smoke_export_paper_log OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
