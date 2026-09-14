# Contributing to Bitget Divergent Agent Desk

Thank you for your interest in contributing to **Bitget Divergent Agent Desk**! We welcome contributions ranging from signal math refinements and machine learning filters to exchange execution optimizations and dashboard UI features.

---

## 🚀 Quick Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/scanner72/bitget-bot.git
   cd bitget-bot
   ```

2. **Create Python Virtual Environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   pip install pytest ruff
   ```

3. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Add your Bitget Demo API credentials
   ```

4. **Launch Development Stack**:
   ```bash
   # Windows:
   .\start.ps1
   # Linux / macOS:
   ./start.sh
   ```

---

## 📐 Architecture Guidelines

- **Zero Unbounded Risk**: Never bypass the risk gate (`risk/gate.py`). All orders must be dynamically sized to the Stop-Loss distance.
- **Paper Shadow First**: Test new order types and soft-exit algorithms using `EXEC_MODE=paper` or `EXEC_MODE=hub_demo` before considering live execution.
- **Public Data Priority**: Keep market data streams 100% public (via WebSockets/REST bootstrap) without requiring API keys.

---

## 🧪 Testing Policy

Run the test suite before submitting pull requests:
```bash
pytest tests/ -v
```
