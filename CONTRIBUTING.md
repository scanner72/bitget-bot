# Contributing

Desk for Bitget S2 Agentic Trading. Public OHLCV, Demo UTA only unless the owner explicitly enables live.

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Checks

There is no `tests/` package. Run the offline smokes:

```bash
./test.sh          # Windows: .\test.ps1
```

Hub/Demo scripts (`smoke_bitget.py`, `smoke_hub_demo.py`) need local Demo keys — do not add them to CI.

## Rules

- Do not bypass `risk/gate.py`.
- Do not commit `.env` or `data/`.
- Keep docs aligned with `api/app.py` and `.env.example`.
- `TF_BLOCKER_ENABLED` stays off unless the owner asks.
