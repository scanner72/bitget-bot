<!-- CONTEXT-SYNC-START -->
## 🔄 Multi-Agent Sync (ContextSync)
> 🕒 Project: **Bitget-Divergent-Agent-Desk** | 🤖 Fleet: **Cursor, Claude, Antigravity, Windsurf**

### 🧠 Central Knowledge Store:
- Find shared decisions: invoke `context_search(query="...", project="bitget-bot")`
- Save architecture decisions: invoke `context_save(title="...", content="...", project="bitget-bot")`
<!-- CONTEXT-SYNC-END -->

# Bitget Divergent Agent Desk: Developer & Claude Reference

## 🚀 Quick Commands

### Stack Management (Docker Compose)
```bash
# Start full containerized stack (Dashboard + Desk Loop)
docker compose up -d

# View live logs
docker compose logs -f

# Stop containers
docker compose down
```

### Local Python Development
```bash
# Activate virtual environment
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Launch FastAPI Dashboard (Port 8080)
python scripts/run_api.py

# Launch Background Desk Signal Loop
python scripts/run_signal_loop.py --poll

# Run Smoke Tests & Diagnostics
python scripts/smoke_account.py
python scripts/smoke_signal.py
python scripts/smoke_risk.py
python scripts/smoke_paper.py
```

---

## 🏗️ Architecture & Module Map

- `ingest/candle_cache.py`: Real-time circular buffer of historical and WebSocket candles.
- `signals/momentum_divergence.py`: Mathematical detection of RSI vs price divergences.
- `agent/decide.py`: Evaluates candidates, applying trend/regime filters.
- `risk/gate.py`: Strict limit validation (cooldown, max notional, daily loss).
- `risk/sizing.py`: Position sizing based on distance to Stop-Loss.
- `exec/bitget_hub.py`: Bitget UTA Demo/Live execution interface.
- `exec/paper.py`: In-memory shadow book handling soft exits (TP1, Break-Even, trailing).
- `api/app.py`: FastAPI server serving endpoints and reactive web dashboard.

---

## 📏 Coding Standards

- Python 3.11+ with strict type hinting (`from __future__ import annotations`).
- Never perform blocking network calls inside signal evaluation loops.
- Handle Bitget API rate limits gracefully with exponential backoff.
