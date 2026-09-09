"""Execution router: paper | hub_demo | live(guarded).

hub_demo: Bitget UTA Demo (paptrading) + local paper shadow for SL/TP UI/risk.
"""
from __future__ import annotations

import os
from typing import Any

from exec.paper import PaperBook, close_paper, open_paper


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
            f"[HUB] SL MOVE {reason} {pos.get('symbol')} -> {client._round_px(new_f, str(pos.get('symbol')))} "
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

    if mode == "live":
        allow = (os.getenv("BITGET_ALLOW_LIVE") or "").strip().lower()
        if allow not in {"1", "true", "yes"}:
            raise RuntimeError("EXEC_MODE=live blocked (set BITGET_ALLOW_LIVE=1)")

    if mode in {"hub_demo", "live"}:
        from exec.bitget_hub import BitgetUtaClient

        client = BitgetUtaClient.from_env()
        if mode == "hub_demo" and not client.demo:
            raise RuntimeError("hub_demo requires BITGET_DEMO=1 / paptrading client")
        if mode == "live" and client.demo:
            raise RuntimeError("live mode but client is in demo/paptrading")
        qty = _qty_from_size(size_usd, price)
        placed = client.place_perp_market(symbol, side, qty)
        meta["hub_order_id"] = placed.get("orderId")
        meta["hub_client_oid"] = placed.get("clientOid")
        meta["hub_qty"] = qty
        print(
            f"[HUB] OPEN {mode} {side} {symbol} qty={qty} @~{price} "
            f"orderId={placed.get('orderId')}"
        )
        # Exchange hard SL + TP2 (parachute if bot dies). Soft TP1/BE/trail stay local.
        sl_raw = meta.get("sl")
        tp2_raw = meta.get("tp2")
        if (sl_raw is not None and str(sl_raw).strip() != "") or (
            tp2_raw is not None and str(tp2_raw).strip() != ""
        ):
            try:
                br = client.place_position_tpsl(
                    symbol,
                    side,
                    stop_loss=sl_raw,
                    take_profit=tp2_raw,
                )
                meta["hub_tpsl_order_id"] = br.get("orderId")
                meta["hub_tpsl_client_oid"] = br.get("clientOid")
                if sl_raw is not None and str(sl_raw).strip() != "":
                    meta["hub_sl_order_id"] = br.get("orderId")
                    meta["hub_sl_client_oid"] = br.get("clientOid")
                    meta["hub_sl_price"] = client._round_px(sl_raw, symbol)
                if tp2_raw is not None and str(tp2_raw).strip() != "":
                    meta["hub_tp2_order_id"] = br.get("orderId")
                    meta["hub_tp2_price"] = client._round_px(tp2_raw, symbol)
                print(
                    f"[HUB] TPSL {side} {symbol} sl={sl_raw} tp2={tp2_raw} "
                    f"orderId={br.get('orderId')}"
                )
            except Exception as exc:  # noqa: BLE001
                meta["hub_tpsl_error"] = f"{type(exc).__name__}: {exc}"
                print(f"[HUB] TPSL ERROR {symbol}: {exc}")

    # Keep paper size_usd as risk/target notional (do NOT overwrite with exchange margin).
    return open_paper(
        symbol=symbol,
        side=side,
        size_usd=size_usd,
        price=price,
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
    if pos is not None and mode in {"hub_demo", "live"}:
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
                if str(it.get("symbol") or "") == want and str(it.get("posSide") or "").lower() == side_l:
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
    return close_paper(
        position_id_or_symbol,
        price,
        meta=close_meta,
        gate=gate,
        book=b,
    )
