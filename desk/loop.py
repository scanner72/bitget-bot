"""Multi-symbol candle -> signal -> candidate -> agent decide -> risk log.

Config from env / .env:
  SYMBOLS            comma-separated (BTCUSDT or BTC/USDT:USDT); used when SCAN_MODE=fixed
  SCAN_MODE          fixed|auto (default auto) — auto = top crypto + rToken USDT-M perps
  SCAN_CRYPTO_TOP    default 20
  SCAN_RTOKEN_TOP    default 20
  SCAN_REFRESH_SEC   default 300; 0 = refresh every pass
  TIMEFRAME          default 15m
  POLL_SEC           default 60
  ONCE=1             single pass then exit
  OHLCV_LIMIT        default 200 (faster auto scans); raise for deeper history

NO SPOT — Bitget USDT-M swap + rToken/RWA stock perps only.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from desk.candidate_log import CandidateLog, candidate_from_signal
from desk.pipeline import evaluate_candidate
from risk.gate import RiskGate
from risk.exits import ExitConfig, check_open_exits
from ingest.bitget_ohlcv import fetch_ohlcv, set_shared_exchange
from ingest.symbols import to_display
from ingest.universe import UniverseCache, load_scan_env, resolve_scan_symbols
from signals.engine import run_full_detection

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAIR_CONFIG = {
    "rsi_length": 14,
    "mom_period": 10,
    "lookback_left": 5,
    "lookback_right": 5,
    "min_bars": 5,
    "max_bars": 50,
}


@dataclass
class LoopConfig:
    symbols: list[str]
    timeframe: str = "15m"
    poll_sec: float = 60.0
    once: bool = False
    ohlcv_limit: int = 200
    candidates_path: Path = ROOT / "data" / "candidates.jsonl"
    decisions_path: Path = ROOT / "data" / "decisions.jsonl"
    pair_config: dict[str, Any] | None = None
    scan_mode: str = "auto"
    scan_crypto_top: int = 20
    scan_rtoken_top: int = 20
    scan_refresh_sec: float = 300.0
    fixed_symbols: list[str] = field(default_factory=list)

    @property
    def risk_decisions_path(self) -> Path:
        """Alias: decisions JSONL (agent + risk chain)."""
        return self.decisions_path


def normalize_symbol(raw: str) -> str:
    """Map BTCUSDT / BTC/USDT -> Bitget ccxt swap BTC/USDT:USDT."""
    s = raw.strip().upper().replace("-", "/")
    if not s:
        return s
    if ":" in s:
        return s
    if "/" in s:
        return f"{s}:USDT"
    for quote in ("USDT", "USDC"):
        if s.endswith(quote) and len(s) > len(quote):
            base = s[: -len(quote)]
            return f"{base}/{quote}:USDT"
    return s


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def load_config(env_path: Path | None = None) -> LoopConfig:
    load_dotenv(env_path or (ROOT / ".env"), override=False)
    raw_symbols = os.getenv("SYMBOLS", "BTC/USDT:USDT")
    symbols = [normalize_symbol(p) for p in raw_symbols.split(",") if p.strip()]
    if not symbols:
        symbols = ["BTC/USDT:USDT"]
    timeframe = os.getenv("TIMEFRAME", "15m").strip() or "15m"
    try:
        poll_sec = float(os.getenv("POLL_SEC", "60") or "60")
    except ValueError:
        poll_sec = 60.0
    # Default 200 for scan speed; override via OHLCV_LIMIT
    try:
        ohlcv_limit = int(os.getenv("OHLCV_LIMIT", "200") or "200")
    except ValueError:
        ohlcv_limit = 200
    cand = os.getenv("CANDIDATES_PATH", "").strip()
    candidates_path = Path(cand) if cand else (ROOT / "data" / "candidates.jsonl")
    dec_raw = (
        os.getenv("DECISIONS_PATH", "").strip()
        or os.getenv("RISK_DECISIONS_PATH", "").strip()
    )
    decisions_path = Path(dec_raw) if dec_raw else (ROOT / "data" / "decisions.jsonl")
    scan = load_scan_env()
    return LoopConfig(
        symbols=list(symbols),
        timeframe=timeframe,
        poll_sec=max(1.0, poll_sec),
        once=_env_bool("ONCE", True),
        ohlcv_limit=max(50, ohlcv_limit),
        candidates_path=candidates_path,
        decisions_path=decisions_path,
        pair_config=dict(DEFAULT_PAIR_CONFIG),
        scan_mode=scan["mode"],
        scan_crypto_top=scan["crypto_top"],
        scan_rtoken_top=scan["rtoken_top"],
        scan_refresh_sec=scan["refresh_sec"],
        fixed_symbols=list(symbols),
    )


def process_symbol(
    symbol: str,
    cfg: LoopConfig,
    clog: CandidateLog,
    gate: RiskGate | None = None,
) -> dict[str, Any]:
    """Fetch -> detect -> log candidate -> agent.decide -> risk. Returns summary."""
    summary: dict[str, Any] = {
        "symbol": symbol,
        "ok": False,
        "bars": 0,
        "has_zones": False,
        "candidate": None,
        "logged": False,
        "deduped": False,
        "action": None,
        "risk_allowed": None,
        "risk_reason": None,
        "error": None,
    }
    try:
        df = fetch_ohlcv(symbol=symbol, timeframe=cfg.timeframe, limit=cfg.ohlcv_limit)
        summary["bars"] = len(df)
        signal, has_zones = run_full_detection(df, cfg.pair_config or DEFAULT_PAIR_CONFIG)
        summary["has_zones"] = bool(has_zones)
        summary["ok"] = True
        if signal is None:
            return summary
        rec = candidate_from_signal(
            signal,
            symbol=symbol,
            timeframe=cfg.timeframe,
            ts=datetime.now(timezone.utc),
        )
        summary["candidate"] = rec["type"]
        if clog.is_duplicate(rec):
            summary["deduped"] = True
            return summary
        written = clog.append(rec)
        summary["logged"] = bool(written)
        summary["deduped"] = not written
        if written and gate is not None:
            out = evaluate_candidate(
                rec,
                gate,
                decisions_path=cfg.decisions_path,
                context={
                    "symbol": symbol,
                    "timeframe": cfg.timeframe,
                    "ohlcv_df": df,
                    "ohlcv_limit": cfg.ohlcv_limit,
                },
            )
            summary["action"] = out.get("action")
            summary["risk_allowed"] = out.get("allowed")
            summary["risk_reason"] = out.get("reason")
        return summary
    except Exception as exc:  # noqa: BLE001
        summary["error"] = f"{type(exc).__name__}: {exc}"
        return summary


def _active_symbols(
    cfg: LoopConfig,
    cache: UniverseCache | None,
) -> tuple[list[str], UniverseCache | None]:
    """Resolve symbols for this pass (auto refresh or fixed SYMBOLS)."""
    if cfg.scan_mode != "auto":
        return list(cfg.fixed_symbols or cfg.symbols), cache
    if cache is None:
        cache = UniverseCache()
        set_shared_exchange(cache.exchange)
    symbols, _mode, snap = resolve_scan_symbols(
        cfg.fixed_symbols or cfg.symbols,
        cache=cache,
    )
    cfg.symbols = list(symbols)
    if snap is not None:
        print(
            f"[universe] crypto_top={len(snap.crypto)}/{snap.crypto_total} "
            f"rtoken_top={len(snap.rtoken)}/{snap.rtoken_total} "
            f"union={len(symbols)}"
        )
    return symbols, cache


def run_pass(
    cfg: LoopConfig,
    clog: CandidateLog,
    gate: RiskGate | None = None,
    *,
    symbols: list[str] | None = None,
) -> list[dict[str, Any]]:
    use = symbols if symbols is not None else cfg.symbols
    results = [process_symbol(sym, cfg, clog, gate) for sym in use]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = []
    for r in results:
        if r["error"]:
            parts.append(f"{to_display(r['symbol']) or r['symbol']}:ERR({r['error']})")
        elif r["candidate"]:
            flag = "LOG" if r["logged"] else ("DEDUP" if r["deduped"] else "CAND")
            agent_bit = ""
            if r.get("action"):
                agent_bit = f" action={r['action']}"
            risk_bit = ""
            if r.get("risk_allowed") is not None:
                risk_bit = (
                    f" risk={'ALLOW' if r['risk_allowed'] else 'DENY'}"
                    f":{r.get('risk_reason')}"
                )
            elif r.get("action") == "SKIP":
                risk_bit = f" skip_reason={r.get('risk_reason')}"
            parts.append(
                f"{to_display(r['symbol']) or r['symbol']}:{r['candidate']}[{flag}] zones={r['has_zones']} "
                f"bars={r['bars']}{agent_bit}{risk_bit}"
            )
        else:
            parts.append(f"{to_display(r['symbol']) or r['symbol']}:EMPTY zones={r['has_zones']} bars={r['bars']}")
    logged_n = sum(1 for r in results if r.get("logged"))
    print(f"[{ts}] pass symbols={len(results)} logged={logged_n} | " + " | ".join(parts))
    return results


def run_loop(cfg: LoopConfig | None = None) -> int:
    cfg = cfg or load_config()
    clog = CandidateLog(cfg.candidates_path)
    gate = RiskGate()
    mode = "ONCE" if cfg.once else f"POLL/{cfg.poll_sec}s"
    cache: UniverseCache | None = None
    if cfg.scan_mode == "auto":
        cache = UniverseCache()
        set_shared_exchange(cache.exchange)
    print(
        f"desk.loop start mode={mode} scan={cfg.scan_mode} tf={cfg.timeframe} "
        f"ohlcv_limit={cfg.ohlcv_limit} "
        f"crypto_top={cfg.scan_crypto_top} rtoken_top={cfg.scan_rtoken_top} "
        f"refresh={cfg.scan_refresh_sec}s "
        f"fixed_symbols={cfg.fixed_symbols} out={cfg.candidates_path} "
        f"decisions={cfg.decisions_path}"
    )
    exit_cfg = ExitConfig.from_env()
    while True:
        symbols, cache = _active_symbols(cfg, cache)
        run_pass(cfg, clog, gate, symbols=symbols)
        try:
            check_open_exits(
                cfg=exit_cfg,
                timeframe=cfg.timeframe,
                ohlcv_limit=min(80, max(50, cfg.ohlcv_limit)),
            )
        except Exception as _exit_exc:  # noqa: BLE001
            print(f"[EXIT] check error: {_exit_exc}")
        if cfg.once:
            print("desk.loop done (ONCE)")
            return 0
        time.sleep(cfg.poll_sec)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--once" in argv:
        os.environ["ONCE"] = "1"
    if "--poll" in argv:
        os.environ["ONCE"] = "0"
    return run_loop(load_config())


if __name__ == "__main__":
    raise SystemExit(main())
