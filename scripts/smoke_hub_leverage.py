"""Offline: hub opens call UTA set-leverage 20x before place-order; closes do not."""
from __future__ import annotations

import os
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

        def set_position_stop_loss(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("exchange rejected stop")

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
    with patch.dict(
        os.environ,
        {"EXEC_MODE": "hub_demo", "BITGET_DEMO": "1", "HUB_SYNC_EXCHANGE_SL": "1"},
        clear=False,
    ), patch(
        "exec.bitget_hub.BitgetUtaClient.from_env",
        return_value=stop_client,
    ):
        first = sync_exchange_sl(stop_pos, 344.42, reason="be_timeout")
        _assert(first is not None and first.get("hub_sl_sync_error"), first)
        stop_pos["meta"].update(first)
        second = sync_exchange_sl(stop_pos, 344.42, reason="be_timeout")
        _assert(second is None, second)
        _assert(stop_client.calls == 1, stop_client.calls)
        third = sync_exchange_sl(stop_pos, 345.0, reason="trailing")
        _assert(third is not None and third.get("hub_sl_sync_error"), third)
        _assert(stop_client.calls == 2, stop_client.calls)

    print("smoke_hub_leverage OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
