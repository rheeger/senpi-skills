# Senpi Fee Optimization (ALO) — Guide for Trading Agents

## What Changed

Senpi now supports `FEE_OPTIMIZED_LIMIT` as an `orderType` on `create_position`, `close_position`, and `edit_position`. This places your order as a maker (Add Liquidity Only) instead of crossing the spread as a taker.

## Why It Matters

| | Taker (MARKET) | Maker (ALO) |
|---|---|---|
| Hyperliquid fee (Tier 0) | 4.5 bps (0.045%) | 1.5 bps (0.015%) |
| Senpi builder fee | 5 bps | 5 bps |
| **Round-trip cost** | **~19 bps** | **~13 bps** |

That's a 67% reduction in Hyperliquid exchange fees per side (4.5 bps → 1.5 bps). On a round-trip, you save 6 bps in exchange fees.

At 10x leverage on a $1,000 margin position ($10K notional), taker round-trip HL fees = $9.00 vs maker round-trip = $3.00. You save $6.00 per round-trip.

**Note:** These are Tier 0 (base) rates. Higher-volume traders on better tiers save less in absolute terms but ALO is still cheaper at every tier. At Tier 4+ ($500M+ volume), maker fees drop to 0 bps.

## How To Use It

### Three modes:

**1. Aggressive (default, unchanged)**
```
orderType: "MARKET"
```
Immediate fill. Highest fees. Use when speed matters more than cost — fast-moving momentum entries, emergency exits, stop losses.

**2. Fee-optimized with guaranteed fill**
```
orderType: "FEE_OPTIMIZED_LIMIT"
ensureExecutionAsTaker: true
```
Places a maker order. If it doesn't fill within 60 seconds, automatically falls back to a market order. You always get filled, but the call blocks for up to 60s. Best default for most trading agents.

**3. Fee-optimized, resting**
```
orderType: "FEE_OPTIMIZED_LIMIT"
ensureExecutionAsTaker: false  (or omit)
```
Places a maker order that stays on the book until filled or cancelled. No automatic fallback. You need to monitor via `strategy_get_open_orders` and cancel with `cancel_order` if needed. Use when you're patient and want guaranteed maker rate.

### Constraints
- `limitPrice`, `timeInForce`, and `slippagePercent` cannot be used with `FEE_OPTIMIZED_LIMIT`
- TP/SL can still be set alongside ALO orders
- `strategy_close` always uses market orders internally — if you want fee-optimized exits, close each position individually with `close_position` first, then call `strategy_close`
- `edit_position` also supports `FEE_OPTIMIZED_LIMIT` — use it when adjusting margin or modifying positions non-urgently

## Detecting Maker vs Taker Execution

Both `create_position` and `close_position` return `executionAsMaker` in the response, inside the `mainOrder` object of the results. Check this field to confirm whether your order was filled as maker or taker:

```json
{
  "results": {
    "mainOrder": {
      "executionAsMaker": true,
      "avgPrice": "3245.50",
      "filledSize": "1.5"
    }
  }
}
```

Use this to:
- Track actual fee costs per trade (maker rate vs taker rate)
- Verify ALO orders are filling as maker (if `executionAsMaker: false` with ALO, it fell back to taker)
- Build fee analytics over time — what percentage of your trades actually get maker rate

## When To Use Each Mode

### Use ALO (fee-optimized) for:
- **Planned entries** where you have a thesis and 60 seconds won't change it — "go long ETH 10x" based on a signal from 5 minutes ago
- **Take-profit exits** where you're already in profit and can wait for a better fill
- **Scaling into positions** — adding to a winner where timing isn't critical
- **Margin adjustments** via `edit_position` — no urgency, save on fees
- **Any trade where the alpha comes from the position, not the entry tick** — which is most trades

### Use MARKET for:
- **Stop losses** — always. When your SL triggers, you need out NOW. A 60s delay at -3% ROE can become -6% ROE
- **Momentum entries** where the signal is time-sensitive — breakout detected 2 seconds ago, price is moving fast
- **Emergency exits** — position going wrong, liquidation risk
- **Closing positions during strategy_close** if you don't care about the last few bps

### Hybrid approach (recommended for most agents):
```
Entries:  FEE_OPTIMIZED_LIMIT + ensureExecutionAsTaker: true
Closes:   MARKET (for stops/emergencies), ALO (for take-profits)
SL/TP:    Always MARKET
```

This saves ~3 bps on every entry while keeping exits instant when they need to be.

## Fee Math: Hybrid Approach (Realistic Scenario)

Most agents will use maker on entry and taker on exit (stop losses must be market). Here's the math at Tier 0:

| | Entry | Exit | Round-Trip |
|---|---|---|---|
| Both taker | 4.5 bps | 4.5 bps | **9.0 bps** |
| Hybrid (maker entry, taker exit) | 1.5 bps | 4.5 bps | **6.0 bps** |
| Both maker | 1.5 bps | 1.5 bps | **3.0 bps** |

**Hybrid saves 3 bps per round-trip** — a 33% reduction in HL exchange fees.

On a $10K notional position:
- Both taker: $9.00 in HL fees
- Hybrid: $6.00 in HL fees
- Saving: **$3.00 per round-trip**

At 10x leverage on $1,000 margin, that $3.00 saving is 0.30% ROE you keep. Across 5 trades/day = $15/day or ~$450/month.

## What I Learned Running It (Real Data)

I ran a hedged volume cycling strategy with ALO to test it at scale. Key observations:

**ALO entries work.** Orders fill as maker, confirmed by `executionAsMaker: true` in the response. Entry fill times range from 30-85 seconds (vs instant for market).

**The 60s blocking call matters.** If you're opening multiple positions that depend on each other (hedges, pairs), the sequential 60s waits create timing risk. Position A fills in 5s, position B waits 55s — by then the market has moved and your hedge is born lopsided.

**Don't use ALO for time-sensitive closes.** I tested ALO closes on hedge timeout exits (positions that need to close flat). The 60s delay turned $0-cost flat closes into $2-16 losses per close. Switching to MARKET closes fixed this.

## Quick Start

Before your first trade in a session, ask the user:
> "Would you like aggressive execution (market order, immediate fill) or fee-optimized (maker order, lower fees with up to 60s fill time)?"

Then apply their preference to all subsequent orders. For most users who aren't scalping, fee-optimized with guaranteed fill is the right default.
