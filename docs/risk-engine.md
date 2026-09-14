# 🛡️ Mathematical Risk Management Engine

The **Risk Engine** in Bitget S2 Divergent Agent Desk is responsible for capital preservation, position sizing, exposure bounds, and execution circuit breakers.

---

## 1. Risk Control Parameters

All risk parameters are configured via environment variables in `.env`:

| Parameter | Environment Variable | Default Value | Description |
|:---|:---|:---:|:---|
| **Risk Per Trade** | `RISK_USD_PER_TRADE` | `$2.00` | Target dollar loss if position hits Stop-Loss. |
| **Max Notional** | `MAX_NOTIONAL_USD` | `$100.00` | Hard cap on total position notional size. |
| **Min Notional** | `MIN_NOTIONAL_USD` | `$10.00` | Minimum viable notional required to submit an order. |
| **Daily Loss Limit** | `MAX_DAILY_LOSS_USD` | `$50.00` | Global killswitch halting all entries if exceeded. |
| **Max Open Positions** | `MAX_POSITIONS` | `8` | Maximum concurrent active positions allowed. |
| **Single Symbol Limit** | `ONE_POSITION_PER_SYMBOL` | `true` | Prevents pyramiding or doubling down on same ticker. |
| **Cooldown Period** | `COOLDOWN_SEC` | `900` (15 min) | Time delay required before re-entering the same symbol. |
| **Signal Type Filter** | `ALLOWED_TYPES` | All | Restricts signals (e.g. `BULLISH_DIV,BEARISH_DIV`). |

---

## 2. Risk-to-SL Dynamic Sizing Formula

Rather than trading arbitrary fixed quantities, position notional is mathematically calculated from the distance between Entry and Stop-Loss:

$$\text{SL Distance Ratio} = \frac{|\text{Entry Price} - \text{SL Price}|}{\text{Entry Price}}$$

$$\text{Calculated Notional (USD)} = \frac{\text{RISK\_USD\_PER\_TRADE}}{\text{SL Distance Ratio}}$$

$$\text{Final Notional} = \max(\text{MIN\_NOTIONAL\_USD}, \min(\text{MAX\_NOTIONAL\_USD}, \text{Calculated Notional}))$$

### Practical Example:
- Entry: **BTC at $60,000**
- Stop-Loss: **$59,400** (1.0% distance = 0.01)
- Risk Target: **$2.00**
- Raw Sizing: $\$2.00 / 0.01 = \$200.00$
- Constrained by `MAX_NOTIONAL_USD = $100.00` ➔ Final Notional: **$100.00** (Actual max loss = $1.00).

---

## 3. Circuit Breakers & State Persistence

- **Daily Loss Guard**: The risk engine tracks cumulative closed PnL + open unrealized losses. If losses hit `MAX_DAILY_LOSS_USD`, all pending orders are blocked until 00:00 UTC.
- **State File (`data/risk_state.json`)**: Persists daily loss counters and active cooldown timestamps across process restarts.
