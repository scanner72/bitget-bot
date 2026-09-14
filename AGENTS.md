<!-- CONTEXT-SYNC-START -->
## 🔄 Multi-Agent Sync (ContextSync)
> 🕒 Project: **Bitget-Divergent-Agent-Desk** | 🤖 Fleet: **Cursor, Claude, Antigravity, Windsurf**

### 🧠 Central Knowledge Store:
- Find shared decisions: invoke `context_search(query="...", project="bitget-bot")`
- Save architecture decisions: invoke `context_save(title="...", content="...", project="bitget-bot")`
<!-- CONTEXT-SYNC-END -->

# 🤖 Bitget Divergent Agent Desk: AI Agent Fleet Guidelines & Rules

This document defines the operating rules, boundaries, and safety constraints for AI Agents (Antigravity, Cursor, Claude, Windsurf) working on the Bitget Divergent Agent Desk platform.

---

## 🧭 1. General Project Context
- **Name**: Bitget S2 Divergent Agent Desk
- **Domain**: Quantitative algorithmic trading agent with RSI-momentum divergence signals, mathematical risk gates, Bitget Demo UTA routing, and shadow book soft exits.
- **Key Safety Rule**: Trading derivatives carries substantial financial risk. The codebase defaults strictly to `EXEC_MODE=hub_demo` and `BITGET_DEMO=1`.

---

## 💻 2. Technical Stack & Rules

### 🐍 Backend & Agent Engine (Python 3.11+)
- **Frameworks**: FastAPI, Uvicorn, CCXT, NumPy, Pandas, WebSockets.
- **Risk Gate**: Every single trade must be audited by `risk/gate.py`. Bypassing the risk gate is strictly prohibited.
- **Demo Mode**: Real orders must only be placed on the Bitget Universal Trading Account Demo endpoint (`paptrading`).

### 🛡️ 3. State & Memory Conventions
- Decisions are appended to `data/decisions.jsonl`.
- Risk state is saved to `data/risk_state.json`.
- Do not commit runtime JSONL or JSON files located in `data/`.
