"""Execution router: paper | hub_demo | live(guarded).

hub_demo: Bitget UTA Demo (paptrading) + local paper shadow for SL/TP UI/risk.
"""
from __future__ import annotations

import os
import time
from typing import Any

from exec.paper import PaperBook, close_paper, open_paper
from exec.demo_universe import (
    drop_demo_symbol,
    is_missing_pair_error,
    is_paper_venue,
    paper_fallback_enabled,
    symbol_tradable_on_demo,
)


def exec_mode() -> str:
    mode = (os.getenv("EXEC_MODE") or "paper").strip().lower()
    if mode in {"hub_demo", "demo"}:
        return "hub_demo"
    if mode in {"live", "hub_live"}:
        return "live"
    return "paper"


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
            "hub_tpsl_order_id": out.get("orderId") or meta.get("hub_tpsl_order_id"),
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[HUB] SL MOVE ERROR {pos.get('symbol')}: {exc}")
        return {"hub_sl_sync_error": f"{type(exc).__name__}: {exc}"}


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

    if mode in {"hub_demo", "live"}:
        from exec.bitget_hub import BitgetUtaClient

        client = BitgetUtaClient.from_env()
        if mode == "hub_demo" and not client.demo:
            raise RuntimeError("hub_demo requires BITGET_DEMO=1 / paptrading client")
        if mode == "live" and client.demo:
            raise RuntimeError("live mode but client is in demo/paptrading")
        qty = _qty_from_size(size_usd, signal_price)
        try:
            placed = client.place_perp_market(symbol, side, qty)
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
            raise
        meta["exec_venue"] = "hub"
        meta["hub_order_id"] = placed.get("orderId")
        meta["hub_client_oid"] = placed.get("clientOid")
        meta["hub_qty"] = qty
        print(
            f"[HUB] OPEN {mode} {side} {symbol} qty={qty} @~{signal_price} "
            f"orderId={placed.get('orderId')}"
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
        except Exception as exc:  # noqa: BLE001
            hub_meta = {"hub_close_error": f"{type(exc).__name__}: {exc}"}
            print(f"[HUB] CLOSE ERROR {exc}")

    close_meta = dict(meta or {})
    close_meta.update(hub_meta)
    close_meta.setdefault("exec_mode", mode)
    if pos is not None and is_paper_venue(pos):
        close_meta.setdefault("exec_venue", "paper")
    return close_paper(
        position_id_or_symbol,
        price,
        meta=close_meta,
        gate=gate,
        book=b,
    )
