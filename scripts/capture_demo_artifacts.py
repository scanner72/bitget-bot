"""Capture sanitized local Demo API responses for the public S2 evidence pack."""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "demo_artifacts"
BASE = "http://127.0.0.1:8080"

JSON_ROUTES = {
    "health.json": "/health",
    "equity.json": "/equity",
    "positions.json": "/positions",
    "fills.json": "/fills?limit=100",
    "history.json": "/history?limit=200",
    "decisions.json": "/decisions?limit=100",
    "candidates.json": "/candidates?limit=100",
}

SECRET_PARTS = (
    "api_key",
    "apikey",
    "secret",
    "passphrase",
    "password",
    "authorization",
    "private_key",
)


def fetch(path: str) -> bytes:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=20) as response:  # noqa: S310
        return response.read()


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): clean(item)
            for key, item in value.items()
            if not any(part in str(key).lower() for part in SECRET_PARTS)
        }
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def main() -> int:
    health = clean(json.loads(fetch("/health").decode("utf-8")))
    if not health.get("ok"):
        print(f"error: local API is not healthy: {health}")
        return 1
    if health.get("exec_mode") != "hub_demo" or not health.get("bitget_demo"):
        print(f"error: refusing non-Demo artifact capture: {health}")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    for name, route in JSON_ROUTES.items():
        payload = health if route == "/health" else clean(
            json.loads(fetch(route).decode("utf-8"))
        )
        (OUT / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {OUT / name}")

    html = fetch("/").decode("utf-8", errors="replace")
    (OUT / "snapshot.html").write_text(html, encoding="utf-8")
    print(f"wrote {OUT / 'snapshot.html'}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
