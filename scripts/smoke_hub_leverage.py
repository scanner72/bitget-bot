"""Offline: hub opens call UTA set-leverage 20x before place-order; closes do not."""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _client():
    from exec.bitget_hub import BitgetUtaClient

    return BitgetUtaClient(
        api_key="k",
        secret_key="s",
        passphrase="p",
        demo=True,
    )


def main() -> int:
    from exec.bitget_hub import hub_leverage
    from exec.router import sync_exchange_sl

    os.environ.pop("HUB_LEVERAGE", None)
    _assert(hub_leverage() == 20, hub_leverage())
    with patch.dict(os.environ, {"HUB_LEVERAGE": "10"}, clear=False):
        _assert(hub_leverage() == 10, hub_leverage())
    with patch.dict(os.environ, {"HUB_LEVERAGE": "999"}, clear=False):
        _assert(hub_leverage() == 125, hub_leverage())

    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(self, method, path, *, query=None, body=None):  # noqa: ARG001
        calls.append((method, path, body))
        if path == "/api/v3/account/set-leverage":
            return {"code": "00000", "data": "success"}
        if path == "/api/v3/trade/place-order":
            return {"code": "00000", "data": {"orderId": "oid-1", "clientOid": "c1"}}
        raise AssertionError(path)

    client = _client()
    client.request = fake_request.__get__(client, type(client))  # type: ignore[method-assign]
    with patch.dict(os.environ, {"HUB_LEVERAGE": "20"}, clear=False):
        placed = client.place_perp_market("BTC/USDT:USDT", "long", "0.01")
    _assert(placed.get("orderId") == "oid-1", placed)
    _assert(len(calls) >= 2, calls)
    _assert(calls[0][1] == "/api/v3/account/set-leverage", calls[0])
    _assert((calls[0][2] or {}).get("leverage") == "20", calls[0])
    _assert((calls[0][2] or {}).get("symbol") == "BTCUSDT", calls[0])
    _assert((calls[0][2] or {}).get("category") == "USDT-FUTURES", calls[0])
    _assert((calls[0][2] or {}).get("marginMode") == "crossed", calls[0])
    _assert(calls[1][1] == "/api/v3/trade/place-order", calls[1])

    calls.clear()
    client.place_perp_market("BTC/USDT:USDT", "long", "0.02")
    _assert(
        all(p != "/api/v3/account/set-leverage" for _, p, _ in calls),
        calls,
    )
    _assert(calls[0][1] == "/api/v3/trade/place-order", calls)

    fresh = _client()
    fresh.request = fake_request.__get__(fresh, type(fresh))  # type: ignore[method-assign]
    calls.clear()
    fresh.close_perp_market("ETH/USDT:USDT", "long", "0.5")
    _assert(
        all(p != "/api/v3/account/set-leverage" for _, p, _ in calls),
        calls,
    )
    _assert(any(p == "/api/v3/trade/place-order" for _, p, _ in calls), calls)

    isolated = _client()

    def isolated_request(self, method, path, *, query=None, body=None):  # noqa: ARG001
        calls.append((method, path, body))
        if path == "/api/v3/account/set-leverage":
            if "posSide" not in (body or {}):
                raise RuntimeError("Bitget API error code=400 msg=posSide required isolated")
            _assert((body or {}).get("posSide") == "short", body)
            _assert((body or {}).get("marginMode") == "isolated", body)
            return {"code": "00000", "data": "success"}
        raise AssertionError(path)

    calls.clear()
    isolated.request = isolated_request.__get__(isolated, type(isolated))  # type: ignore[method-assign]
    isolated.ensure_leverage("SOL/USDT:USDT", pos_side="short")
    _assert(len(calls) == 2, calls)

    live = {
        "list": [
            {
                "symbol": "SUIUSDT",
                "posSide": "long",
                "total": "100",
                "leverage": "1",
            },
            {
                "symbol": "BTCUSDT",
                "posSide": "long",
                "total": "0.01",
                "leverage": "20",
            },
        ]
    }
    sync_client = _client()
    sync_calls: list[tuple[str, str, dict | None]] = []

    def sync_request(self, method, path, *, query=None, body=None):  # noqa: ARG001
        sync_calls.append((method, path, body))
        if path == "/api/v3/account/set-leverage":
            return {"code": "00000", "data": "success"}
        raise AssertionError(path)

    sync_client.request = sync_request.__get__(sync_client, type(sync_client))  # type: ignore[method-assign]
    with patch.dict(os.environ, {"HUB_LEVERAGE": "20"}, clear=False):
        n = sync_client.sync_open_positions_leverage(live)
    _assert(n == 1, n)
    _assert(len(sync_calls) == 1, sync_calls)
    _assert((sync_calls[0][2] or {}).get("symbol") == "SUIUSDT", sync_calls[0])

    class StopClient:
        def __init__(self) -> None:
            self.calls = 0
            self.sent: list[float] = []

        def set_position_stop_loss(self, symbol, position_side, stop_loss, **kwargs):  # noqa: ARG002
            self.calls += 1
            self.sent.append(float(stop_loss))
            raise RuntimeError("exchange rejected stop")

    def _refuse_network(*_args, **_kwargs):
        raise AssertionError("smoke_hub_leverage attempted a live network call")

    stop_client = StopClient()
    stop_pos = {
        "symbol": "GOOGL/USDT:USDT",
        "side": "long",
        "tp2": 361.69,
        "meta": {
            "exec_venue": "hub",
            "hub_sl_price": "337.51",
            "hub_sl_order_id": "sl-1",
        },
    }
    # CI (2026-09-26) fetched a live GOOGL mark ~343.84, clamped the requested
    # long SL 344.42 down to 343.67, and stored that clamped price. The next
    # identical 344.42 request no longer matched, so the skip did not fire.
    # Mark and pricePlace are fixed here; the clamp must still happen, and
    # the retry key stays the requested SL.
    with patch.dict(
        os.environ,
        {"EXEC_MODE": "hub_demo", "BITGET_DEMO": "1", "HUB_SYNC_EXCHANGE_SL": "1"},
        clear=False,
    ), patch(
        "exec.bitget_hub.BitgetUtaClient.from_env",
        return_value=stop_client,
    ), patch(
        "ingest.bitget_ohlcv.get_mark_price",
        return_value=343.84,
    ), patch(
        "exec.bitget_hub.price_decimals_for_symbol",
        return_value=2,
    ), patch.object(
        socket.socket, "connect", _refuse_network
    ), patch(
        "socket.create_connection", _refuse_network
    ):
        first = sync_exchange_sl(stop_pos, 344.42, reason="be_timeout")
        _assert(first is not None and first.get("hub_sl_sync_error"), first)
        _assert(abs(float(first["hub_sl_sync_attempt_price"]) - 344.42) < 1e-9, first)
        _assert(stop_client.calls == 1, stop_client.calls)
        _assert(abs(stop_client.sent[0] - 343.67) < 1e-9, stop_client.sent)
        stop_pos["meta"].update(first)
        second = sync_exchange_sl(stop_pos, 344.42, reason="be_timeout")
        _assert(second is None, second)
        _assert(stop_client.calls == 1, stop_client.calls)
        third = sync_exchange_sl(stop_pos, 345.0, reason="trailing")
        _assert(third is not None and third.get("hub_sl_sync_error"), third)
        _assert(abs(float(third["hub_sl_sync_attempt_price"]) - 345.0) < 1e-9, third)
        _assert(stop_client.calls == 2, stop_client.calls)
        _assert(abs(stop_client.sent[1] - 343.67) < 1e-9, stop_client.sent)

    # 25590/25592: keep the working strategy order; do not place a fresh bracket.
    def _keep_on_side_error(code: str) -> None:
        keeper = _client()
        placed_fresh = {"n": 0}

        def _modify_reject(self, **kwargs):  # noqa: ARG001
            raise RuntimeError(
                f"Bitget API error code={code} msg=stop on wrong side of mark"
            )

        def _place_fresh(self, *args, **kwargs):  # noqa: ARG001
            placed_fresh["n"] += 1
            return {"orderId": "fresh"}

        keeper.modify_strategy_order = _modify_reject.__get__(keeper, type(keeper))  # type: ignore[method-assign]
        keeper.place_position_tpsl = _place_fresh.__get__(keeper, type(keeper))  # type: ignore[method-assign]
        raised = False
        try:
            keeper.set_position_stop_loss(
                "BTC/USDT:USDT",
                "long",
                100.0,
                order_id="sl-keep",
                take_profit=120.0,
            )
        except RuntimeError as exc:
            raised = True
            _assert(code in str(exc), exc)
        _assert(raised, code)
        _assert(placed_fresh["n"] == 0, (code, placed_fresh))

    with patch(
        "exec.bitget_hub.price_decimals_for_symbol", return_value=2
    ), patch.object(
        socket.socket, "connect", _refuse_network
    ), patch(
        "socket.create_connection", _refuse_network
    ):
        for code in ("25590", "25592"):
            _keep_on_side_error(code)

        other = _client()
        placed_other = {"n": 0}

        def _modify_other(self, **kwargs):  # noqa: ARG001
            raise RuntimeError("Bitget API error code=40001 msg=temporary")

        def _place_other(self, *args, **kwargs):  # noqa: ARG001
            placed_other["n"] += 1
            return {"orderId": "fresh-other"}

        other.modify_strategy_order = _modify_other.__get__(other, type(other))  # type: ignore[method-assign]
        other.place_position_tpsl = _place_other.__get__(other, type(other))  # type: ignore[method-assign]
        moved = other.set_position_stop_loss(
            "BTC/USDT:USDT", "long", 100.0, order_id="sl-other"
        )
        _assert(moved.get("orderId") == "fresh-other", moved)
        _assert(placed_other["n"] == 1, placed_other)

    # Demo hub mark wins over a higher stored/public mark (long SL must sit below it).
    demo_client = StopClient()
    demo_pos = {
        "symbol": "GOOGL/USDT:USDT",
        "side": "long",
        "mark_price": 360.0,
        "tp2": 361.69,
        "meta": {
            "exec_venue": "hub",
            "hub_sl_price": "330.00",
            "hub_sl_order_id": "sl-demo",
            "hub_mark_at_open": 360.0,
            "mark_price": 360.0,
        },
    }
    with patch.dict(
        os.environ,
        {"EXEC_MODE": "hub_demo", "BITGET_DEMO": "1", "HUB_SYNC_EXCHANGE_SL": "1"},
        clear=False,
    ), patch(
        "exec.bitget_hub.BitgetUtaClient.from_env",
        return_value=demo_client,
    ), patch(
        "exec.router._fetch_hub_mark",
        return_value=340.0,
    ), patch(
        "ingest.bitget_ohlcv.get_mark_price",
        return_value=350.0,
    ), patch(
        "exec.bitget_hub.price_decimals_for_symbol",
        return_value=2,
    ), patch.object(
        socket.socket, "connect", _refuse_network
    ), patch(
        "socket.create_connection", _refuse_network
    ):
        demo_out = sync_exchange_sl(demo_pos, 344.42, reason="be_timeout")
    _assert(demo_out is not None and demo_out.get("hub_sl_sync_error"), demo_out)
    _assert(abs(float(demo_out["hub_sl_sync_attempt_price"]) - 344.42) < 1e-9, demo_out)
    _assert(demo_client.calls == 1, demo_client.calls)
    _assert(abs(demo_client.sent[0] - 339.83) < 1e-9, demo_client.sent)

    stored_client = StopClient()
    stored_pos = {
        "symbol": "GOOGL/USDT:USDT",
        "side": "long",
        "tp2": 361.69,
        "meta": {
            "exec_venue": "hub",
            "hub_sl_price": "330.00",
            "hub_sl_order_id": "sl-stored",
            "hub_mark_at_open": 340.0,
        },
    }
    with patch.dict(
        os.environ,
        {"EXEC_MODE": "hub_demo", "BITGET_DEMO": "1", "HUB_SYNC_EXCHANGE_SL": "1"},
        clear=False,
    ), patch(
        "exec.bitget_hub.BitgetUtaClient.from_env",
        return_value=stored_client,
    ), patch(
        "exec.router._fetch_hub_mark",
        return_value=None,
    ), patch(
        "ingest.bitget_ohlcv.get_mark_price",
        return_value=350.0,
    ), patch(
        "exec.bitget_hub.price_decimals_for_symbol",
        return_value=2,
    ), patch.object(
        socket.socket, "connect", _refuse_network
    ), patch(
        "socket.create_connection", _refuse_network
    ):
        stored_out = sync_exchange_sl(stored_pos, 344.42, reason="be_timeout")
    _assert(stored_out is not None and stored_out.get("hub_sl_sync_error"), stored_out)
    _assert(stored_client.calls == 1, stored_client.calls)
    _assert(abs(stored_client.sent[0] - 339.83) < 1e-9, stored_client.sent)

    print("smoke_hub_leverage OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
