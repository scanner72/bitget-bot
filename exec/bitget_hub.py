"""Bitget UTA v3 Demo/live client (Agent Hub–compatible REST).

Uses paptrading=1 when BITGET_DEMO=1 / EXEC_MODE=hub_demo.
Credentials from env: BITGET_API_KEY / BITGET_SECRET_KEY / BITGET_PASSPHRASE
(or BITGET_DEMO_* aliases).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://api.bitget.com"

_PRICE_PLACE_CACHE: dict[str, int] = {}


def price_decimals_for_symbol(symbol: str, default: int = 2) -> int:
    """Bitget mix contract pricePlace for USDT-FUTURES (cached)."""
    sym = ccxt_to_bitget_symbol(symbol)
    if sym in _PRICE_PLACE_CACHE:
        return _PRICE_PLACE_CACHE[sym]
    env_key = f"BITGET_PRICE_DECIMALS_{sym}"
    raw = _env(env_key)
    if raw.isdigit():
        _PRICE_PLACE_CACHE[sym] = int(raw)
        return int(raw)
    try:
        from urllib.request import urlopen

        url = (
            f"{BASE_URL}/api/v2/mix/market/contracts"
            f"?productType=USDT-FUTURES&symbol={sym}"
        )
        payload = json.loads(urlopen(url, timeout=10).read().decode("utf-8"))
        data = payload.get("data") or []
        row = data[0] if isinstance(data, list) and data else {}
        place = int(row.get("pricePlace") or default)
    except Exception:
        place = default
    _PRICE_PLACE_CACHE[sym] = place
    return place



def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def demo_mode_enabled() -> bool:
    mode = _env("EXEC_MODE", "paper").lower()
    if mode in {"hub_demo", "demo"}:
        return True
    flag = _env("BITGET_DEMO", "0").lower()
    return flag in {"1", "true", "yes", "on"}


def load_credentials() -> tuple[str, str, str]:
    key = _env("BITGET_API_KEY") or _env("BITGET_DEMO_API_KEY")
    secret = _env("BITGET_SECRET_KEY") or _env("BITGET_DEMO_SECRET_KEY")
    passphrase = _env("BITGET_PASSPHRASE") or _env("BITGET_DEMO_PASSPHRASE")
    if not (key and secret and passphrase):
        raise RuntimeError(
            "Missing Bitget API credentials "
            "(BITGET_API_KEY / BITGET_SECRET_KEY / BITGET_PASSPHRASE)"
        )
    return key, secret, passphrase


def ccxt_to_bitget_symbol(symbol: str) -> str:
    """CRCL/USDT:USDT -> CRCLUSDT."""
    s = (symbol or "").strip().upper()
    if not s:
        return s
    if "/" in s:
        base, rest = s.split("/", 1)
        quote = rest.split(":", 1)[0]
        return f"{base}{quote}"
    return s.replace("-", "").replace("_", "")


@dataclass
class BitgetUtaClient:
    api_key: str
    secret_key: str
    passphrase: str
    demo: bool = True
    timeout_sec: float = 20.0

    @classmethod
    def from_env(cls) -> "BitgetUtaClient":
        key, secret, passphrase = load_credentials()
        return cls(
            api_key=key,
            secret_key=secret,
            passphrase=passphrase,
            demo=demo_mode_enabled(),
            timeout_sec=float(_env("BITGET_HTTP_TIMEOUT_SEC", "20") or "20"),
        )

    def _sign(self, ts: str, method: str, path: str, body: str) -> str:
        prehash = f"{ts}{method.upper()}{path}{body}"
        digest = hmac.new(
            self.secret_key.encode("utf-8"),
            prehash.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode("utf-8")

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        method = method.upper()
        q = ""
        if query:
            q = "?" + urlencode({k: v for k, v in query.items() if v is not None})
        full_path = path + q
        raw_body = ""
        if body is not None:
            raw_body = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        ts = str(int(time.time() * 1000))
        sign = self._sign(ts, method, full_path, raw_body)
        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": ts,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }
        if self.demo:
            headers["paptrading"] = "1"
        req = Request(
            BASE_URL + full_path,
            data=raw_body.encode("utf-8") if raw_body else None,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(req, timeout=self.timeout_sec) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                raise RuntimeError(f"Bitget HTTP {exc.code}: {raw[:300]}") from exc
            raise RuntimeError(
                f"Bitget HTTP {exc.code} code={payload.get('code')} msg={payload.get('msg')}"
            ) from exc
        if str(payload.get("code")) not in {"00000", "0"}:
            raise RuntimeError(
                f"Bitget API error code={payload.get('code')} msg={payload.get('msg')}"
            )
        return payload

    def account_assets(self) -> dict[str, Any]:
        return self.request("GET", "/api/v3/account/assets")

    def usdt_snapshot(self) -> dict[str, Any]:
        """Parse /api/v3/account/assets into USDT equity/available."""
        payload = self.account_assets()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            data = {}

        def _f(v: Any, default: float = 0.0) -> float:
            try:
                if v is None or v == "":
                    return default
                return float(v)
            except (TypeError, ValueError):
                return default

        account_equity = _f(data.get("accountEquity"))
        usdt_equity = _f(data.get("usdtEquity"))
        unrealised_pnl = _f(data.get("usdtUnrealisedPnl"))
        available = 0.0
        balance = 0.0
        assets = data.get("assets")
        if isinstance(assets, list):
            for row in assets:
                if not isinstance(row, dict):
                    continue
                coin = str(row.get("coin") or row.get("currency") or "").upper()
                if coin != "USDT":
                    continue
                available = _f(row.get("available"), available)
                balance = _f(row.get("balance"), balance)
                eq = row.get("equity")
                if eq is not None and eq != "":
                    usdt_equity = _f(eq, usdt_equity)
                break
        if usdt_equity <= 0 and account_equity > 0:
            usdt_equity = account_equity
        if available <= 0 and balance > 0:
            available = balance
        if balance <= 0 and available > 0:
            balance = available
        if account_equity <= 0 and usdt_equity > 0:
            account_equity = usdt_equity
        return {
            "account_equity": account_equity,
            "usdt_equity": usdt_equity,
            "available": available,
            "balance": balance,
            "unrealised_pnl": unrealised_pnl,
            "source": "hub_demo" if self.demo else "hub_live",
        }


    def current_positions(self, category: str = "USDT-FUTURES") -> Any:
        data = self.request(
            "GET",
            "/api/v3/position/current-position",
            query={"category": category},
        )
        return data.get("data")

    def place_order(self, **params: Any) -> dict[str, Any]:
        """POST /api/v3/trade/place-order — params per UTA Place-Order docs."""
        if "clientOid" not in params:
            params["clientOid"] = f"bg{uuid.uuid4().hex[:16]}"
        data = self.request("POST", "/api/v3/trade/place-order", body=params)
        return data.get("data") or {}

    def cancel_order(
        self,
        *,
        category: str,
        symbol: str,
        order_id: str | None = None,
        client_oid: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"category": category, "symbol": symbol}
        if order_id:
            body["orderId"] = str(order_id)
        if client_oid:
            body["clientOid"] = str(client_oid)
        data = self.request("POST", "/api/v3/trade/cancel-order", body=body)
        return data.get("data") or {}

    def place_perp_limit(
        self,
        symbol: str,
        side: str,
        qty: str,
        price: str,
        *,
        pos_side: str | None = None,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        """Convenience: USDT-FUTURES limit. side buy/sell; pos_side long/short."""
        bitget_symbol = ccxt_to_bitget_symbol(symbol)
        side_l = side.lower()
        if side_l in {"long", "buy"}:
            order_side = "buy"
            default_pos = "long"
        elif side_l in {"short", "sell"}:
            order_side = "sell"
            default_pos = "short"
        else:
            raise ValueError(f"invalid side: {side}")
        body: dict[str, Any] = {
            "category": "USDT-FUTURES",
            "symbol": bitget_symbol,
            "side": order_side,
            "posSide": (pos_side or default_pos),
            "orderType": "limit",
            "price": str(price),
            "qty": str(qty),
            "timeInForce": "gtc",
        }
        if reduce_only:
            body["reduceOnly"] = "yes"
        return self.place_order(**body)


    def place_perp_market(
        self,
        symbol: str,
        side: str,
        qty: str,
        *,
        pos_side: str | None = None,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        """USDT-FUTURES market. side long/buy or short/sell; pos_side long/short."""
        bitget_symbol = ccxt_to_bitget_symbol(symbol)
        side_l = side.lower()
        if side_l in {"long", "buy"}:
            order_side = "buy"
            default_pos = "long"
        elif side_l in {"short", "sell"}:
            order_side = "sell"
            default_pos = "short"
        else:
            raise ValueError(f"invalid side: {side}")
        body: dict[str, Any] = {
            "category": "USDT-FUTURES",
            "symbol": bitget_symbol,
            "side": order_side,
            "posSide": (pos_side or default_pos),
            "orderType": "market",
            "qty": str(qty),
        }
        if reduce_only:
            body["reduceOnly"] = "yes"
        return self.place_order(**body)

    def close_perp_market(
        self,
        symbol: str,
        position_side: str,
        qty: str,
    ) -> dict[str, Any]:
        """Market close in hedge mode: long->sell/posSide=long (no reduceOnly; UTA rejects both)."""
        pos = position_side.lower()
        if pos in {"long", "buy"}:
            close_side = "sell"
            pos_side = "long"
        elif pos in {"short", "sell"}:
            close_side = "buy"
            pos_side = "short"
        else:
            raise ValueError(f"invalid position_side: {position_side}")
        # UTA error 25238 if posSide + reduceOnly together
        return self.place_perp_market(
            symbol,
            close_side,
            qty,
            pos_side=pos_side,
            reduce_only=False,
        )


    def place_strategy_order(self, **params: Any) -> dict[str, Any]:
        """POST /api/v3/trade/place-strategy-order (tpsl / trigger / ...)."""
        if "clientOid" not in params:
            params["clientOid"] = f"bg{uuid.uuid4().hex[:16]}"
        data = self.request("POST", "/api/v3/trade/place-strategy-order", body=params)
        return data.get("data") or {}

    def _round_px(self, price: float | str, symbol: str | None = None) -> str:
        if symbol:
            decimals = price_decimals_for_symbol(symbol)
        else:
            decimals = int((_env("BITGET_SL_PRICE_DECIMALS", "2") or "2"))
        step = 10 ** decimals
        px = round(float(price) * step) / step
        return f"{px:.{decimals}f}"

    def _close_side_for_pos(self, position_side: str) -> tuple[str, str]:
        pos = position_side.lower()
        if pos in {"long", "buy"}:
            return "long", "sell"
        if pos in {"short", "sell"}:
            return "short", "buy"
        raise ValueError(f"invalid position_side: {position_side}")

    def place_position_tpsl(
        self,
        symbol: str,
        position_side: str,
        *,
        stop_loss: float | str | None = None,
        take_profit: float | str | None = None,
        trigger_by: str = "mark",
        tpsl_mode: str = "full",
        qty: str | None = None,
    ) -> dict[str, Any]:
        """Exchange full/partial TPSL. At least one of stop_loss / take_profit required."""
        if stop_loss is None and take_profit is None:
            raise ValueError("need stop_loss and/or take_profit")
        pos_side, close_side = self._close_side_for_pos(position_side)
        trig = trigger_by if trigger_by in {"mark", "market"} else "mark"
        body: dict[str, Any] = {
            "category": "USDT-FUTURES",
            "symbol": ccxt_to_bitget_symbol(symbol),
            "type": "tpsl",
            "tpslMode": tpsl_mode,
            "side": close_side,
            "posSide": pos_side,
        }
        if stop_loss is not None and str(stop_loss).strip() != "":
            body["stopLoss"] = self._round_px(stop_loss, symbol)
            body["slTriggerBy"] = trig
            body["slOrderType"] = "market"
        if take_profit is not None and str(take_profit).strip() != "":
            body["takeProfit"] = self._round_px(take_profit, symbol)
            body["tpTriggerBy"] = trig
            body["tpOrderType"] = "market"
        if tpsl_mode == "partial":
            if not qty:
                raise ValueError("qty required for partial tpsl")
            body["qty"] = str(qty)
        return self.place_strategy_order(**body)

    def place_position_stop_loss(
        self,
        symbol: str,
        position_side: str,
        stop_loss: float | str,
        *,
        trigger_by: str = "mark",
        tpsl_mode: str = "full",
        qty: str | None = None,
    ) -> dict[str, Any]:
        """Back-compat: SL-only bracket."""
        return self.place_position_tpsl(
            symbol,
            position_side,
            stop_loss=stop_loss,
            trigger_by=trigger_by,
            tpsl_mode=tpsl_mode,
            qty=qty,
        )

    def modify_strategy_order(self, **params: Any) -> dict[str, Any]:
        """POST /api/v3/trade/modify-strategy-order."""
        data = self.request("POST", "/api/v3/trade/modify-strategy-order", body=params)
        return data.get("data") or {}


    def set_position_stop_loss(
        self,
        symbol: str,
        position_side: str,
        stop_loss: float | str,
        *,
        order_id: str | None = None,
        client_oid: str | None = None,
        take_profit: float | str | None = None,
        trigger_by: str = "mark",
    ) -> dict[str, Any]:
        """Move/update exchange SL on existing tpsl order; keep TP if provided."""
        sl_s = self._round_px(stop_loss, symbol)
        trig = trigger_by if trigger_by in {"mark", "market"} else "mark"
        if order_id or client_oid:
            body: dict[str, Any] = {
                "stopLoss": sl_s,
                "slTriggerBy": trig,
                "slOrderType": "market",
            }
            if order_id:
                body["orderId"] = str(order_id)
            if client_oid:
                body["clientOid"] = str(client_oid)
            if take_profit is not None and str(take_profit).strip() != "":
                body["takeProfit"] = self._round_px(take_profit, symbol)
                body["tpTriggerBy"] = trig
                body["tpOrderType"] = "market"
            try:
                return self.modify_strategy_order(**body)
            except Exception as exc:  # noqa: BLE001
                print(f"[HUB] modify SL failed, place new: {exc}")
        return self.place_position_tpsl(
            symbol,
            position_side,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trigger_by=trigger_by,
        )

    def set_position_take_profit(
        self,
        symbol: str,
        position_side: str,
        take_profit: float | str,
        *,
        order_id: str | None = None,
        client_oid: str | None = None,
        stop_loss: float | str | None = None,
        trigger_by: str = "mark",
    ) -> dict[str, Any]:
        """Add/update TP on an existing strategy order, else place TP-only tpsl."""
        tp_s = self._round_px(take_profit, symbol)
        trig = trigger_by if trigger_by in {"mark", "market"} else "mark"
        if order_id or client_oid:
            body: dict[str, Any] = {
                "takeProfit": tp_s,
                "tpTriggerBy": trig,
                "tpOrderType": "market",
            }
            if order_id:
                body["orderId"] = str(order_id)
            if client_oid:
                body["clientOid"] = str(client_oid)
            if stop_loss is not None and str(stop_loss).strip() != "":
                body["stopLoss"] = self._round_px(stop_loss, symbol)
                body["slTriggerBy"] = trig
                body["slOrderType"] = "market"
            try:
                return self.modify_strategy_order(**body)
            except Exception as exc:  # noqa: BLE001
                print(f"[HUB] modify TP failed, place new: {exc}")
        return self.place_position_tpsl(
            symbol,
            position_side,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trigger_by=trigger_by,
        )
