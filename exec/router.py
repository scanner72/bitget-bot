"""Execution router: paper | hub_demo | live(guarded).

hub_demo: Bitget UTA Demo (paptrading) + local paper shadow for SL/TP UI/risk.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

from exec.paper import PaperBook, close_paper, open_paper
from exec.demo_universe import (
    NotOnDemoError,
    drop_demo_symbol,
    is_missing_pair_error,
    is_paper_venue,
    paper_fallback_enabled,
    symbol_tradable_on_demo,
)


class DemoPriceMismatchError(RuntimeError):
    """Hub Demo/live mark or fill is on a different scale than public candles."""


def exec_mode() -> str:
    mode = (os.getenv("EXEC_MODE") or "paper").strip().lower()
    if mode in {"hub_demo", "demo"}:
        return "hub_demo"
    if mode in {"live", "hub_live"}:
        return "live"
    return "paper"


def _qty_ref_price(symbol: str, fallback: float) -> float:
    """Live mark for hub qty; fallback is bar close already validated by pipeline."""
    try:
        from ingest.bitget_ohlcv import fetch_mark_price

        mark = float(fetch_mark_price(symbol))
        if mark > 0:
            return mark
    except Exception as exc:  # noqa: BLE001
        print(f"[HUB] mark fetch warn {symbol}: {exc}")
    fb = float(fallback)
    if fb <= 0:
        raise ValueError("qty ref price must be > 0")
    return fb


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _max_price_dev_pct(symbol: str | None = None) -> float:
    """Public-vs-Demo price sanity cap. rToken/stock can override via env.

    Demo books drift a few % from public (BZ stocks ~4.5%, LTC crypto ~3%).
    Default 2.5% for all — the old crypto 5% let LTC@59.78 vs public ~58 through.
    """
    base = max(0.0, _env_float("SIGNAL_PRICE_MAX_DEV_PCT", 2.5))
    if symbol:
        try:
            from ingest.universe import is_rtoken_symbol

            if is_rtoken_symbol(symbol):
                return max(0.0, _env_float("RTOKEN_SIGNAL_PRICE_MAX_DEV_PCT", base))
        except Exception:  # noqa: BLE001
            return base
    return base


def _price_dev_pct(a: float, b: float) -> float | None:
    try:
        aa = float(a)
        bb = float(b)
    except (TypeError, ValueError):
        return None
    if aa <= 0 or bb <= 0:
        return None
    return abs(aa / bb - 1.0) * 100.0


def _price_scale_reason(
    ref: float,
    other: float | None,
    *,
    label: str,
    symbol: str | None = None,
) -> str | None:
    """None when other is missing or within the symbol's max price deviation."""
    max_dev = _max_price_dev_pct(symbol)
    if max_dev <= 0 or other is None:
        return None
    dev = _price_dev_pct(other, ref)
    if dev is None or dev <= max_dev:
        return None
    return f"{label}:{other} vs ref={ref} dev={dev:.2f}%>{max_dev}"


def _fetch_hub_mark(client: Any, symbol: str) -> float | None:
    """Venue mark/last (Demo when paptrading=1). None if the ticker is unavailable."""
    if not hasattr(client, "request"):
        return None
    try:
        from exec.bitget_hub import ccxt_to_bitget_symbol

        bg = ccxt_to_bitget_symbol(symbol)
        payload = client.request(
            "GET",
            "/api/v3/market/tickers",
            query={"category": "USDT-FUTURES", "symbol": bg},
        )
        data = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(data, dict):
            data = data.get("list") or []
        row: Any = None
        if isinstance(data, list) and data:
            row = data[0]
        elif isinstance(data, dict):
            row = data
        if not isinstance(row, dict):
            return None
        for key in ("markPrice", "lastPrice", "indexPrice"):
            px = _safe_float(row.get(key), None)
            if px is not None and px > 0:
                return px
    except Exception as exc:  # noqa: BLE001
        print(f"[HUB] venue mark fetch warn {symbol}: {exc}")
    return None


def _flatten_hub_open(
    client: Any,
    symbol: str,
    side: str,
    qty: str,
    meta: dict[str, Any],
    *,
    reason: str,
) -> None:
    last_exc: Exception | None = None
    for _ in range(2):
        try:
            closed = client.close_perp_market(symbol, side, str(qty))
            meta["hub_mismatch_close_order_id"] = closed.get("orderId")
            print(
                f"[HUB] FLATTEN {reason} {side} {symbol} qty={qty} "
                f"orderId={closed.get('orderId')}"
            )
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(f"[HUB] FLATTEN ERROR {symbol}: {exc}")
            time.sleep(0.25)
    if last_exc is not None:
        meta["hub_mismatch_close_error"] = f"{type(last_exc).__name__}: {last_exc}"


def _qty_from_size(size_usd: float, price: float, *, decimals: int = 4) -> str:
    px = float(price)
    if px <= 0:
        raise ValueError("price must be > 0")
    qty = float(size_usd) / px
    # floor to step-ish precision so we do not exceed exchange lot after rounding up
    factor = 10 ** int(decimals)
    qty = int(qty * factor) / factor
    if qty <= 0:
        raise ValueError("qty rounded to 0; raise size_usd or check price")
    s = f"{qty:.{int(decimals)}f}".rstrip("0").rstrip(".")
    return s or "0"


def _safe_float(v: Any, default: float | None = None) -> float | None:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _find_hub_position(
    client: Any,
    symbol: str,
    side: str,
    *,
    retries: int = 8,
    delay_sec: float = 0.35,
) -> dict[str, Any] | None:
    """Poll current-position until the just-opened row appears."""
    from exec.bitget_hub import ccxt_to_bitget_symbol

    want = ccxt_to_bitget_symbol(symbol)
    side_l = str(side).lower()
    if side_l in {"buy", "long"}:
        side_l = "long"
    elif side_l in {"sell", "short"}:
        side_l = "short"
    last: dict[str, Any] | None = None
    for _ in range(max(1, retries)):
        try:
            live = client.current_positions() or {}
            items = live.get("list") if isinstance(live, dict) else live
            for it in items or []:
                if not isinstance(it, dict):
                    continue
                if str(it.get("symbol") or "") != want:
                    continue
                if str(it.get("posSide") or "").lower() != side_l:
                    continue
                total = _safe_float(it.get("total"), 0.0) or 0.0
                avail = _safe_float(it.get("available"), 0.0) or 0.0
                if total <= 0 and avail <= 0:
                    continue
                last = it
                entry = _safe_float(it.get("avgPrice") or it.get("openPriceAvg"), None)
                if entry is not None and entry > 0:
                    return it
        except Exception as exc:  # noqa: BLE001
            print(f"[HUB] position poll warn: {exc}")
        time.sleep(delay_sec)
    return last


def _recompute_levels_for_entry(
    meta: dict[str, Any],
    *,
    entry: float,
    side: str,
) -> dict[str, float]:
    """Rebuild SL/TP1/TP2 from ATR using the real fill entry."""
    from risk.atr import levels_from_atr

    atr = _safe_float(meta.get("atr"), None)
    if atr is None or atr <= 0:
        old_entry = _safe_float(
            meta.get("signal_price") or meta.get("provisional_entry"), None
        )
        old_sl = _safe_float(meta.get("sl"), None)
        if old_entry and old_entry > 0 and old_sl is not None:
            atr = abs(old_sl - old_entry)
        else:
            atr = entry * 0.02
    levels = levels_from_atr(entry, side, float(atr))
    return {
        "atr": float(levels["atr"]),
        "sl": float(levels["sl"]),
        "tp1": float(levels["tp1"]),
        "tp2": float(levels["tp2"]),
        "atr_pct": float(levels["atr_pct"]),
    }


def _validate_tpsl_vs_mark(
    side: str,
    *,
    sl: float | None,
    tp: float | None,
    mark: float,
    buffer_pct: float = 0.05,
) -> tuple[float | None, float | None]:
    """Ensure Bitget side rules: short SL>mark & TP<mark; long opposite.

    buffer_pct is percent (0.05 = 0.05%).
    """
    side_l = str(side).lower()
    is_long = side_l in {"long", "buy"}
    buf = max(float(buffer_pct), 0.0) / 100.0
    mark = float(mark)
    out_sl = float(sl) if sl is not None else None
    out_tp = float(tp) if tp is not None else None
    if is_long:
        if out_sl is not None:
            ceiling = mark * (1.0 - buf) if buf > 0 else mark * 0.9999
            if out_sl >= mark:
                out_sl = ceiling
            out_sl = min(out_sl, ceiling)
        if out_tp is not None:
            floor = mark * (1.0 + buf) if buf > 0 else mark * 1.0001
            if out_tp <= mark:
                out_tp = floor
            out_tp = max(out_tp, floor)
    else:
        if out_sl is not None:
            floor = mark * (1.0 + buf) if buf > 0 else mark * 1.0001
            if out_sl <= mark:
                out_sl = floor
            out_sl = max(out_sl, floor)
        if out_tp is not None:
            ceiling = mark * (1.0 - buf) if buf > 0 else mark * 0.9999
            if out_tp >= mark:
                out_tp = ceiling
            out_tp = min(out_tp, ceiling)
    return out_sl, out_tp


def _slippage_bps() -> float:
    raw = (os.getenv("PAPER_FALLBACK_SLIPPAGE_BPS") or "2").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 2.0


def _live_fill_price(symbol: str, side: str, signal_price: float) -> tuple[float, str]:
    """Adverse fill vs live mark (or signal) for paper-live venue."""
    mark = None
    try:
        from ingest.bitget_ohlcv import fetch_mark_price

        mark = float(fetch_mark_price(symbol))
    except Exception as exc:  # noqa: BLE001
        print(f"[PAPER-LIVE] mark fetch warn {symbol}: {exc}")
    base = mark if mark is not None and mark > 0 else float(signal_price)
    if base <= 0:
        raise ValueError("paper-live fill price must be > 0")
    slip = _slippage_bps() / 10000.0
    side_l = str(side).lower()
    is_long = side_l in {"long", "buy"}
    fill = base * (1.0 + slip) if is_long else base * (1.0 - slip)
    src = "live_mark" if mark is not None and mark > 0 else "signal_price"
    return float(fill), src


def _open_paper_live(
    *,
    symbol: str,
    side: str,
    size_usd: float,
    signal_price: float,
    meta: dict[str, Any],
    gate: Any | None,
    book: PaperBook | None,
    reason: str,
) -> str:
    fill, src = _live_fill_price(symbol, side, signal_price)
    meta["exec_venue"] = "paper"
    meta["exec_reason"] = reason
    meta["fill_source"] = src
    meta["hub_skipped"] = True
    meta["provisional_entry"] = signal_price
    levels = _recompute_levels_for_entry(meta, entry=fill, side=side)
    meta.update(levels)
    meta["original_sl"] = levels["sl"]
    meta["tp1_hit"] = False
    meta["trailing_active"] = False
    print(
        f"[PAPER-LIVE] OPEN {side} {symbol} ${size_usd:.0f} "
        f"fill={fill} src={src} reason={reason} "
        f"sl={levels.get('sl')} tp2={levels.get('tp2')}"
    )
    return open_paper(
        symbol=symbol,
        side=side,
        size_usd=size_usd,
        price=fill,
        meta=meta,
        gate=gate,
        book=book,
    )


def _place_hub_tpsl(
    client: Any,
    symbol: str,
    side: str,
    *,
    stop_loss: float | None,
    take_profit: float | None,
    meta: dict[str, Any],
) -> None:
    if stop_loss is None and take_profit is None:
        return
    try:
        br = client.place_position_tpsl(
            symbol,
            side,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        meta["hub_tpsl_order_id"] = br.get("orderId")
        meta["hub_tpsl_client_oid"] = br.get("clientOid")
        meta["hub_tpsl_error"] = None
        if stop_loss is not None:
            meta["hub_sl_order_id"] = br.get("orderId")
            meta["hub_sl_client_oid"] = br.get("clientOid")
            meta["hub_sl_price"] = client._round_px(stop_loss, symbol)
        if take_profit is not None:
            meta["hub_tp2_order_id"] = br.get("orderId")
            meta["hub_tp2_price"] = client._round_px(take_profit, symbol)
        print(
            f"[HUB] TPSL {side} {symbol} sl={stop_loss} tp2={take_profit} "
            f"orderId={br.get('orderId')}"
        )
    except Exception as exc:  # noqa: BLE001
        meta["hub_tpsl_error"] = f"{type(exc).__name__}: {exc}"
        print(f"[HUB] TPSL ERROR {symbol}: {exc}")


def sync_exchange_sl(
    pos: dict[str, Any],
    new_sl: float | str,
    *,
    reason: str = "sl_update",
) -> dict[str, Any] | None:
    """Push local SL to Bitget tpsl when EXEC_MODE is hub_demo/live."""
    mode = exec_mode()
    if mode not in {"hub_demo", "live"}:
        return None
    flag = (os.getenv("HUB_SYNC_EXCHANGE_SL") or "1").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return None
    meta = dict(pos.get("meta") or {})
    try:
        new_f = float(new_sl)
    except (TypeError, ValueError):
        return None
    old = meta.get("hub_sl_price")
    try:
        if old is not None and abs(float(old) - new_f) < 1e-9:
            return None
    except (TypeError, ValueError):
        pass
    # A rejected move at the same target must not be retried on every quote.
    # A genuinely new SL remains eligible for one attempt.
    attempted = meta.get("hub_sl_sync_attempt_price")
    if meta.get("hub_sl_sync_error") and attempted is not None:
        try:
            if abs(float(attempted) - new_f) < 1e-9:
                return None
        except (TypeError, ValueError):
            pass
    if is_paper_venue(pos):
        return None
    if mode == "live":
        allow = (os.getenv("BITGET_ALLOW_LIVE") or "").strip().lower()
        if allow not in {"1", "true", "yes"}:
            return None
    from exec.bitget_hub import BitgetUtaClient

    client = BitgetUtaClient.from_env()
    side = str(pos.get("side") or meta.get("side") or "long")
    tp2 = pos.get("tp2") if pos.get("tp2") is not None else meta.get("tp2")
    tp2 = meta.get("hub_tp2_price") or tp2
    # Clamp SL/TP vs live mark so Bitget 25590 is not hit on BE/trail.
    mark = None
    for src in (
        pos.get("mark_price"),
        meta.get("mark_price"),
        meta.get("hub_mark_at_open"),
    ):
        try:
            if src is not None and float(src) > 0:
                mark = float(src)
                break
        except (TypeError, ValueError):
            pass
    if mark is None:
        try:
            from ingest.bitget_ohlcv import get_mark_price

            mark = float(get_mark_price(str(pos.get("symbol"))))
        except Exception as _mexc:  # noqa: BLE001
            print(f"[HUB] SL mark lookup warn: {_mexc}")
    requested_sl = new_f
    if mark is not None and mark > 0:
        tp_f = None
        try:
            if tp2 is not None and str(tp2).strip() != "":
                tp_f = float(tp2)
        except (TypeError, ValueError):
            tp_f = None
        clamped_sl, clamped_tp = _validate_tpsl_vs_mark(
            side, sl=new_f, tp=tp_f, mark=mark, buffer_pct=0.05
        )
        if clamped_sl is not None:
            if abs(clamped_sl - requested_sl) / max(abs(requested_sl), 1e-12) > 1e-6:
                print(
                    f"[HUB] SL CLAMP {pos.get('symbol')} {requested_sl} -> "
                    f"{clamped_sl} (mark={mark} side={side} reason={reason})"
                )
            new_f = float(clamped_sl)
        if clamped_tp is not None:
            tp2 = clamped_tp
        side_l = str(side).lower()
        is_long = side_l in {"long", "buy"}
        invalid = (is_long and new_f >= mark) or ((not is_long) and new_f <= mark)
        if invalid:
            print(
                f"[HUB] SL SKIP {pos.get('symbol')} sl={new_f} mark={mark} "
                f"(would violate Bitget side rule; reason={reason})"
            )
            return {
                "hub_sl_sync_error": "skipped_invalid_vs_mark",
                "hub_sl_sync_attempt_price": requested_sl,
                "hub_sl_sync_attempt_ts": datetime.now(timezone.utc).isoformat(),
                "hub_sl_sync_reason": reason,
                "hub_sl_skipped_mark": mark,
            }
    try:
        out = client.set_position_stop_loss(
            str(pos.get("symbol")),
            side,
            new_f,
            order_id=meta.get("hub_sl_order_id") or meta.get("hub_tpsl_order_id"),
            client_oid=meta.get("hub_sl_client_oid") or meta.get("hub_tpsl_client_oid"),
            take_profit=tp2,
        )
        print(
            f"[HUB] SL MOVE {reason} {pos.get('symbol')} -> "
            f"{client._round_px(new_f, str(pos.get('symbol')))} "
            f"orderId={out.get('orderId')}"
        )
        return {
            "hub_sl_order_id": out.get("orderId") or meta.get("hub_sl_order_id"),
            "hub_sl_client_oid": out.get("clientOid") or meta.get("hub_sl_client_oid"),
            "hub_sl_price": client._round_px(new_f, str(pos.get("symbol"))),
            "hub_sl_sync_reason": reason,
            "hub_sl_sync_attempt_price": new_f,
            "hub_sl_sync_attempt_ts": datetime.now(timezone.utc).isoformat(),
            "hub_sl_sync_error": None,
            "hub_tpsl_order_id": out.get("orderId") or meta.get("hub_tpsl_order_id"),
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[HUB] SL MOVE ERROR {pos.get('symbol')}: {exc}")
        return {
            "hub_sl_sync_error": f"{type(exc).__name__}: {exc}",
            "hub_sl_sync_attempt_price": new_f,
            "hub_sl_sync_attempt_ts": datetime.now(timezone.utc).isoformat(),
            "hub_sl_sync_reason": reason,
        }


def open_position(
    *,
    symbol: str,
    side: str,
    size_usd: float,
    price: float,
    meta: dict[str, Any] | None = None,
    gate: Any | None = None,
    book: PaperBook | None = None,
) -> str:
    """Open via configured backend. Returns local paper position_id (shadow for hub)."""
    from ingest.symbols import is_trade_denied, to_bitget_id

    if is_trade_denied(symbol):
        raise ValueError(f"symbol_denied:{to_bitget_id(symbol)}")

    mode = exec_mode()
    meta = dict(meta or {})
    meta["exec_mode"] = mode
    signal_price = float(price)
    meta.setdefault("signal_price", signal_price)
    paper_price = signal_price

    if mode == "live":
        allow = (os.getenv("BITGET_ALLOW_LIVE") or "").strip().lower()
        if allow not in {"1", "true", "yes"}:
            raise RuntimeError("EXEC_MODE=live blocked (set BITGET_ALLOW_LIVE=1)")

    if mode == "hub_demo" and paper_fallback_enabled():
        tradable = symbol_tradable_on_demo(symbol)
        if tradable is False:
            return _open_paper_live(
                symbol=symbol,
                side=side,
                size_usd=size_usd,
                signal_price=signal_price,
                meta=meta,
                gate=gate,
                book=book,
                reason="not_on_demo",
            )
    elif mode == "hub_demo":
        tradable = symbol_tradable_on_demo(symbol)
        if tradable is False:
            raise NotOnDemoError(symbol)

    if mode in {"hub_demo", "live"}:
        from exec.bitget_hub import BitgetUtaClient, hub_leverage, calc_adaptive_leverage

        client = BitgetUtaClient.from_env()
        if mode == "hub_demo" and not client.demo:
            raise RuntimeError("hub_demo requires BITGET_DEMO=1 / paptrading client")
        if mode == "live" and client.demo:
            raise RuntimeError("live mode but client is in demo/paptrading")
        qty_px = _qty_ref_price(symbol, signal_price)
        meta["qty_ref_price"] = qty_px
        if mode == "hub_demo":
            demo_mark = _fetch_hub_mark(client, symbol)
            if demo_mark is not None:
                meta["hub_mark_pre_open"] = demo_mark
                mismatch = _price_scale_reason(
                    qty_px, demo_mark, label="demo_mark", symbol=symbol
                )
                if mismatch:
                    meta["hub_price_mismatch"] = mismatch
                    print(f"[HUB] SKIP price scale {symbol}: {mismatch}")
                    raise DemoPriceMismatchError(f"{symbol}: {mismatch}")
        qty = _qty_from_size(size_usd, qty_px)
        sl_val = meta.get("sl")
        if sl_val and signal_price > 0:
            target_lev = calc_adaptive_leverage(signal_price, float(sl_val), default_lev=hub_leverage())
        else:
            target_lev = hub_leverage()
        try:
            placed = client.place_perp_market(symbol, side, qty, leverage=target_lev)
            meta["hub_leverage"] = target_lev
            meta["leverage"] = target_lev
        except Exception as exc:
            if (
                mode == "hub_demo"
                and paper_fallback_enabled()
                and is_missing_pair_error(exc)
            ):
                drop_demo_symbol(symbol)
                print(f"[PAPER-LIVE] hub 25100 {symbol}: {exc}")
                return _open_paper_live(
                    symbol=symbol,
                    side=side,
                    size_usd=size_usd,
                    signal_price=signal_price,
                    meta=meta,
                    gate=gate,
                    book=book,
                    reason="hub_25100",
                )
            if mode == "hub_demo" and is_missing_pair_error(exc):
                drop_demo_symbol(symbol)
                print(f"[HUB] SKIP not on demo {symbol}: {exc}")
                raise NotOnDemoError(f"{symbol}: {exc}") from exc
            raise
        meta["exec_venue"] = "hub"
        meta["hub_order_id"] = placed.get("orderId")
        meta["hub_client_oid"] = placed.get("clientOid")
        meta["hub_qty"] = qty
        print(
            f"[HUB] OPEN {mode} {side} {symbol} qty={qty} @~{qty_px} "
            f"{meta.get('hub_leverage')}x orderId={placed.get('orderId')}"
        )

        # Prefer real exchange avg entry + mark, then rebuild SL/TP from that fill.
        hub_pos = _find_hub_position(client, symbol, side)
        fill_entry = None
        mark = None
        if hub_pos is not None:
            fill_entry = _safe_float(
                hub_pos.get("avgPrice") or hub_pos.get("openPriceAvg"), None
            )
            mark = _safe_float(hub_pos.get("markPrice"), None)
            hub_qty = hub_pos.get("available") or hub_pos.get("total")
            if hub_qty is not None:
                meta["hub_qty"] = str(hub_qty)
        if fill_entry is None or fill_entry <= 0:
            fill_entry = signal_price
            meta["hub_entry_fallback"] = "signal_price"
        else:
            meta["hub_entry"] = fill_entry
        if mark is None or mark <= 0:
            mark = fill_entry
        meta["hub_mark_at_open"] = mark
        mismatch = _price_scale_reason(
            qty_px, fill_entry, label="hub_entry", symbol=symbol
        )
        if mismatch is None:
            mismatch = _price_scale_reason(
                qty_px, mark, label="hub_mark", symbol=symbol
            )
        # Also vs signal bar — public mark can sit between signal and Demo
        # (LTC sig 57.01 / pub 58.02 / Demo 59.78) and still be the wrong scale.
        if mismatch is None and signal_price > 0:
            mismatch = _price_scale_reason(
                signal_price, fill_entry, label="hub_entry_vs_signal", symbol=symbol
            )
        if mismatch:
            meta["hub_price_mismatch"] = mismatch
            flatten_qty = str(meta.get("hub_qty") or qty)
            _flatten_hub_open(
                client,
                symbol,
                side,
                flatten_qty,
                meta,
                reason="price_scale",
            )
            print(f"[HUB] SKIP flatten price scale {symbol}: {mismatch}")
            raise DemoPriceMismatchError(f"{symbol}: {mismatch}")
        paper_price = float(fill_entry)

        levels = _recompute_levels_for_entry(meta, entry=paper_price, side=side)
        meta.update(levels)
        meta["original_sl"] = levels["sl"]
        meta["tp1_hit"] = False
        meta["trailing_active"] = False

        sl_raw = levels.get("sl")
        tp2_raw = levels.get("tp2")
        sl_ok, tp_ok = _validate_tpsl_vs_mark(
            side, sl=sl_raw, tp=tp2_raw, mark=float(mark)
        )
        if sl_ok is not None and sl_raw is not None and abs(sl_ok - float(sl_raw)) > 1e-12:
            meta["sl_adjusted_for_mark"] = True
            meta["sl"] = sl_ok
            meta["original_sl"] = sl_ok
        if tp_ok is not None and tp2_raw is not None and abs(tp_ok - float(tp2_raw)) > 1e-12:
            meta["tp2_adjusted_for_mark"] = True
            meta["tp2"] = tp_ok
        print(
            f"[HUB] LEVELS entry={paper_price} mark={mark} "
            f"sl={sl_ok} tp1={levels.get('tp1')} tp2={tp_ok}"
        )
        if sl_ok is not None or tp_ok is not None:
            _place_hub_tpsl(
                client,
                symbol,
                side,
                stop_loss=sl_ok,
                take_profit=tp_ok,
                meta=meta,
            )

    # Keep paper size_usd as risk/target notional (do NOT overwrite with exchange margin).
    return open_paper(
        symbol=symbol,
        side=side,
        size_usd=size_usd,
        price=paper_price,
        meta=meta,
        gate=gate,
        book=book,
    )


def close_position(
    position_id_or_symbol: str,
    price: float,
    *,
    meta: dict[str, Any] | None = None,
    gate: Any | None = None,
    book: PaperBook | None = None,
) -> dict[str, Any]:
    """Close paper shadow; if hub_demo/live also reduce-only on Bitget."""
    mode = exec_mode()
    b = book or PaperBook(gate=gate)
    if gate is not None and b.gate is None:
        b.gate = gate

    opens = b.list_open()
    key = str(position_id_or_symbol).strip()
    pos = next((p for p in opens if p.get("position_id") == key), None)
    if pos is None:
        pos = next((p for p in opens if p.get("symbol") == key), None)

    hub_meta: dict[str, Any] = {}
    if pos is not None and mode in {"hub_demo", "live"} and not is_paper_venue(pos):
        from exec.bitget_hub import BitgetUtaClient

        if mode == "live":
            allow = (os.getenv("BITGET_ALLOW_LIVE") or "").strip().lower()
            if allow not in {"1", "true", "yes"}:
                raise RuntimeError("EXEC_MODE=live blocked (set BITGET_ALLOW_LIVE=1)")
        client = BitgetUtaClient.from_env()
        side = str(pos.get("side") or "long")
        qty = str(pos.get("qty") or (pos.get("meta") or {}).get("hub_qty") or "")
        # Prefer live Demo/UTA available size (lot rounding may differ from local estimate)
        try:
            live = client.current_positions() or {}
            items = live.get("list") if isinstance(live, dict) else live
            bg = None
            from exec.bitget_hub import ccxt_to_bitget_symbol

            want = ccxt_to_bitget_symbol(str(pos.get("symbol")))
            side_l = str(pos.get("side") or "long").lower()
            for it in items or []:
                if (
                    str(it.get("symbol") or "") == want
                    and str(it.get("posSide") or "").lower() == side_l
                ):
                    bg = it
                    break
            if bg is not None:
                qty = str(bg.get("available") or bg.get("total") or qty)
        except Exception as exc:  # noqa: BLE001
            print(f"[HUB] qty lookup warn: {exc}")
        if not qty:
            size_usd = float(pos.get("size_usd") or 0)
            entry = float(pos.get("entry_price") or price)
            qty = _qty_from_size(size_usd, entry if entry > 0 else price)
        try:
            closed = client.close_perp_market(str(pos.get("symbol")), side, qty)
            hub_meta = {
                "hub_close_order_id": closed.get("orderId"),
                "hub_close_client_oid": closed.get("clientOid"),
            }
            print(
                f"[HUB] CLOSE {mode} {side} {pos.get('symbol')} qty={qty} "
                f"orderId={closed.get('orderId')}"
            )
            # Prefer real Demo fill avg + execPnl over local mark/signal close_price.
            try:
                from exec.reconcile import resolve_hub_close_fill

                fill_px, fill_pnl, fill_meta = resolve_hub_close_fill(
                    pos,
                    order_id=str(closed.get("orderId") or "") or None,
                    client=client,
                )
                hub_meta.update(fill_meta)
                if fill_px is not None and fill_px > 0:
                    price = float(fill_px)
                    hub_meta["close_price_source"] = "hub_fill"
                    hub_meta["hub_close_fill_price"] = float(fill_px)
                    print(
                        f"[HUB] CLOSE FILL {pos.get('symbol')} "
                        f"px={fill_px} exec_pnl={fill_pnl}"
                    )
                else:
                    hub_meta.setdefault("close_price_source", "local_mark_pending_fill")
                    print(
                        f"[HUB] CLOSE FILL pending {pos.get('symbol')}; "
                        f"using trigger px={price}"
                    )
                if fill_pnl is not None:
                    hub_meta["hub_exec_pnl"] = float(fill_pnl)
            except Exception as fill_exc:  # noqa: BLE001
                hub_meta["hub_close_fill_error"] = (
                    f"{type(fill_exc).__name__}: {fill_exc}"
                )
                hub_meta.setdefault("close_price_source", "local_mark_fill_error")
                print(f"[HUB] CLOSE FILL lookup warn: {fill_exc}")
        except Exception as exc:  # noqa: BLE001
            err_s = f"{type(exc).__name__}: {exc}"
            hub_meta = {"hub_close_error": err_s}
            print(f"[HUB] CLOSE ERROR {exc}")
            # Exchange SL/TP often flats first -> 25227 / no position.
            # Still resolve Demo fills so journal matches the exchange.
            already_flat = (
                "25227" in err_s
                or "no position available" in err_s.lower()
                or "position is zero" in err_s.lower()
            )
            if already_flat:
                hub_meta["hub_close_already_flat"] = True
                try:
                    from exec.reconcile import resolve_hub_close_fill

                    fill_px, fill_pnl, fill_meta = resolve_hub_close_fill(
                        pos,
                        order_id=None,
                        client=client,
                    )
                    hub_meta.update(fill_meta)
                    if fill_px is not None and fill_px > 0:
                        price = float(fill_px)
                        hub_meta["close_price_source"] = "hub_fill"
                        hub_meta["hub_close_fill_price"] = float(fill_px)
                        print(
                            f"[HUB] CLOSE FILL (already flat) {pos.get('symbol')} "
                            f"px={fill_px} exec_pnl={fill_pnl}"
                        )
                    else:
                        hub_meta.setdefault(
                            "close_price_source", "local_mark_already_flat"
                        )
                    if fill_pnl is not None:
                        hub_meta["hub_exec_pnl"] = float(fill_pnl)
                except Exception as fill_exc:  # noqa: BLE001
                    hub_meta["hub_close_fill_error"] = (
                        f"{type(fill_exc).__name__}: {fill_exc}"
                    )
                    hub_meta.setdefault(
                        "close_price_source", "local_mark_fill_error"
                    )
                    print(f"[HUB] CLOSE FILL (already flat) warn: {fill_exc}")

    close_meta = dict(meta or {})
    close_meta.update(hub_meta)
    close_meta.setdefault("exec_mode", mode)
    if pos is not None and is_paper_venue(pos):
        close_meta.setdefault("exec_venue", "paper")
    realized = None
    if hub_meta.get("hub_exec_pnl") is not None and hub_meta.get(
        "close_price_source"
    ) == "hub_fill":
        try:
            realized = float(hub_meta["hub_exec_pnl"])
        except (TypeError, ValueError):
            realized = None
    # Always attach default RiskGate so record_close persists (smoke/manual).
    if gate is None and b.gate is None:
        try:
            from risk.gate import RiskGate

            gate = RiskGate()
            b.gate = gate
        except Exception as _gexc:  # noqa: BLE001
            print(f"[RISK] default gate attach skipped: {_gexc}")
    elif gate is not None and b.gate is None:
        b.gate = gate

    out = close_paper(
        position_id_or_symbol,
        price,
        meta=close_meta,
        gate=gate or b.gate,
        book=b,
        realized_pnl=realized,
    )
    try:
        g = gate or b.gate
        if g is not None and hasattr(g, "sync_opens_from_paper"):
            n = g.sync_opens_from_paper(b.list_open())
            print(f"[RISK] post-close sync opens={n}")
    except Exception as _sync_exc:  # noqa: BLE001
        print(f"[RISK] post-close sync skipped: {_sync_exc}")
    return out
