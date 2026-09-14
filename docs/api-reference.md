# 📡 FastAPI Dashboard & Telemetry API Reference

The **FastAPI Gateway** provides real-time telemetry, position monitoring, and execution metrics for the Bitget S2 Divergent Agent Desk.

---

## 1. General Information

- **Default Port**: `8080`
- **Base URL**: `http://127.0.0.1:8080`
- **Response Format**: `application/json` (except `/` HTML dashboard)

---

## 2. Core REST Endpoints

### 2.1 Health Check
- **Endpoint**: `GET /health`
- **Response**:
```json
{
  "status": "ok",
  "exec_mode": "hub_demo",
  "agent_mode": "rules",
  "timestamp": "2026-09-14T11:30:00Z"
}
```

### 2.2 Account & Equity
- **Endpoint**: `GET /account`
- **Description**: Returns wallet balance, unrealized PnL, and margin health from Bitget UTA.
- **Endpoint**: `GET /equity`
- **Response**:
```json
{
  "total_equity": 10420.50,
  "available_margin": 9850.20,
  "unrealized_pnl": 70.30,
  "daily_realized_pnl": 12.40
}
```

### 2.3 Active Positions
- **Endpoint**: `GET /positions`
- **Response**:
```json
[
  {
    "symbol": "BTC/USDT:USDT",
    "side": "long",
    "entry_price": 61250.0,
    "mark_price": 61480.0,
    "size": 0.05,
    "notional": 3074.0,
    "unrealized_pnl": 11.50,
    "sl": 60750.0,
    "tp1": 61850.0,
    "tp2": 62500.0,
    "soft_exit_stage": "BE_ACTIVE"
  }
]
```

### 2.4 Signal Candidates & Agent Decisions
- **Endpoint**: `GET /candidates`
- **Description**: Lists current market symbols showing active RSI divergences.
- **Endpoint**: `GET /decisions`
- **Description**: Stream of recent agent evaluations:
```json
[
  {
    "timestamp": "2026-09-14T11:28:15Z",
    "symbol": "ETH/USDT:USDT",
    "action": "ENTER",
    "reason": "Confirmed Bullish Divergence on 15m; Risk Gate Passed; Notional $50",
    "confidence": 0.88
  }
]
```

### 2.5 Trade Execution Fills & History
- **Endpoint**: `GET /fills`: Chronological log of recent market and bracket order fills.
- **Endpoint**: `GET /history`: Closed positions with win/loss metrics and R-multiples.

### 2.6 Chart Data
- **Endpoint**: `GET /api/chart/data?symbol=BTC/USDT:USDT&timeframe=15m`
- **Description**: Returns OHLCV candles, 14-period RSI array, and detected divergence points for frontend charting.
