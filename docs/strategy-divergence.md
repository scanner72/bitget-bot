# 📈 Quantitative RSI-Momentum Divergence Strategy

The **Divergent Agent Desk** executes structural momentum divergence strategies across liquid cryptocurrency perpetual swaps.

---

## 1. Divergence Mechanics

Divergence occurs when price action and momentum oscillators disagree, signaling exhaustion of the prevailing trend and impending structural mean-reversion.

### Bullish Divergence (Long Entry)
- **Price Action**: Price establishes a **Lower Low (LL)**.
- **RSI Oscillator**: 14-period RSI prints a **Higher Low (HL)**.
- **Significance**: Selling volume and momentum are waning despite lower price print; institutional accumulation underway.

### Bearish Divergence (Short Entry)
- **Price Action**: Price establishes a **Higher High (HH)**.
- **RSI Oscillator**: 14-period RSI prints a **Lower High (LH)**.
- **Significance**: Buying pressure is decelerating; buyer exhaustion preceding distribution breakdown.

---

## 2. Multi-Stage Trade Lifecycle & Soft Exits

```
[ Signal Triggered ] ──► [ Market Entry ] ──► [ Exchange Hard SL + TP2 Placed ]
                                                      │
                                                      ▼
                                       [ Price Reaches 50% to Target (TP1) ]
                                                      │
                                                      ├─► Soft Close: 50% Position Flattened
                                                      └─► SL Moved to Break-Even (BE) on Exchange
                                                      │
                                                      ▼
                                       [ Trailing Stop Activated on Remaining 50% ]
                                                      │
                                       [ Full Fill at TP2 or Trailing Stop Hit ]
```

1. **Entry**: Executed via Market order on Bitget Demo UTA.
2. **Initial Brackets**:
   - **Stop-Loss (SL)**: Anchored below the recent swing low (for longs) or above recent swing high (for shorts).
   - **Take-Profit 2 (TP2)**: Projected institutional target (e.g. 2.0x to 3.0x risk).
3. **Soft TP1 (50% Scaling)**: Monitored locally by `PaperBook`. Once 50% of the target is reached, 50% of the position is closed at market, and the exchange SL is automatically shifted to the entry price (**Break-Even**).
4. **Runner Management**: The remaining 50% runs with dynamic ATR trailing stops until TP2 is hit.
