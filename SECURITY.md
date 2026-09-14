# Security

This bot talks to **Bitget UTA Demo** by default. Live trading is off unless `BITGET_ALLOW_LIVE=1`.

## Keys

- Use Demo Trading keys (`paptrading`). No withdrawal permission.
- Put keys only in local `.env`. Gitignores `.env` and `data/`. `.env.example` is the committed template.
- Bind the dashboard to `127.0.0.1` outside Docker (`scripts/run_api.py` default). Compose sets `HOST=0.0.0.0` for the container.

## Reporting

Use [GitHub private vulnerability reporting](https://github.com/scanner72/bitget-bot/security) on this repository. Do not open a public issue with keys or `.env` contents.
