# 🤖 AI Agent Fleet & Context Sync Integration

**Bitget S2 Divergent Agent Desk** is architected to work seamlessly with modern AI coding assistants (Cursor, Claude Code, Google Antigravity, Windsurf) and persistent cross-machine team memory via **Remote Context (`context-sync`)**.

---

## 1. Supported AI Assistant Fleet

| Agent / Editor | Protocol | Configuration File Location | Status |
|:---|:---:|:---|:---:|
| **Cursor IDE** | Rules | `.cursorrules` in repository root | 🟢 Active |
| **Claude Code CLI** | CLI / Rules | `CLAUDE.md` in repository root | 🟢 Active |
| **Google Antigravity** | Rules / MCP | `AGENTS.md` in repository root | 🟢 Active |
| **Windsurf IDE** | Rules | `.cursorrules` in repository root | 🟢 Active |

---

## 2. Remote Context (`context-sync`) Integration

If you run [Remote Context](https://github.com/scanner72/context-sync) across your development devices, all quantitative strategy adjustments, risk parameter updates, and execution fixes are automatically shared with your whole AI fleet.

### Example Context Memory Call:
```json
// In Cursor, Claude, or Antigravity:
context_save({
  "title": "Bitget Demo Soft TP1 & Break-Even Sync",
  "content": "Configured PaperBook to scale out 50% at TP1 while automatically syncing the exchange SL to Entry Price via Bitget UTA v3 API.",
  "project": "bitget-bot",
  "tags": ["bitget", "uta", "paper-shadow", "risk", "soft-exits"]
})
```
