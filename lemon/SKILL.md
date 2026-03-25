---
name: lemon-strategy
description: >-
  LEMON v1.0 — The Degen Fader. Identifies historically reckless traders
  (DEGEN activity + CHOPPY consistency) on Hyperliquid, monitors their live
  positions, and counter-trades them when they're bleeding at high leverage.
  If a cluster of degens goes max-leverage long on a coin and starts losing,
  LEMON shorts it — betting on their inevitable liquidation cascade.
  Uses DSL v1.1.1 trailing stops for exits. No static TP/SL.
license: MIT
metadata:
  author: jason-goldberg
  version: "1.0"
  platform: senpi
  exchange: hyperliquid
---

# 🍋 LEMON v1.0 — The Degen Fader

Find the worst traders. Wait until they're bleeding. Take the other side.

---

## ⛔ CRITICAL AGENT RULES

### RULE 1: Install path is `/data/workspace/skills/lemon-strategy/`

### RULE 2: THE SCANNER DOES NOT EXIT POSITIONS

When the scanner sees an active position, it outputs NO_REPLY. DSL is the
ONLY exit mechanism. Every Senpi agent that implemented its own exit logic
lost money. The scanner finds entries. DSL manages exits. Period.

### RULE 3: MAX 2 POSITIONS at a time

Check clearinghouse before every entry. If positions >= 2, skip.

### RULE 4: Scanner output is AUTHORITATIVE

Leverage, margin, direction, coin — use exactly what the scanner says.
Do not override from memory or "improve" the parameters.

### RULE 5: Write dslState directly — include wallet address and size

The scanner provides a `dslState` block. Write it to `state/dsl-{COIN}.json`.
After the entry fills, read `strategy_get_clearinghouse_state` to get the
actual position size (`abs(szi)`) and update the `size` field in the DSL
state file. This prevents the DSL crash bug that hit 7+ agents.

### RULE 6: Verify BOTH crons on every session start

Scanner cron AND DSL cron must both show `status: ok`.

### RULE 7: Never modify parameters

Do not adjust leverage, margin, thresholds, DSL settings, or any other
parameter. Every agent that self-modified made things worse.

### RULE 8: 180-minute per-asset cooldown after any exit

---

## Core Thesis

Most copy-trading strategies follow the best traders. LEMON does the opposite:
it finds the WORST traders and bets against them.

Hyperliquid's `discovery_get_top_traders` API exposes trader quality labels:
- **Activity labels:** DEGEN, SNIPER, AGGRESSIVE, BALANCED, CONSERVATIVE
- **Consistency labels:** CHOPPY, STREAKY, RELIABLE, ELITE

DEGEN + CHOPPY traders are statistically the most likely to:
1. Over-leverage (20x+ on volatile assets)
2. Hold losing positions too long (hope trading)
3. Eventually get liquidated (forced cascade)

When a cluster of these traders is max-leveraged and actively bleeding
(-10%+ ROE), their liquidation is increasingly likely. LEMON enters the
opposite direction — SHORT if they're LONG, LONG if they're SHORT — and
rides the liquidation cascade that follows.

**Why this works:** Liquidation cascades are mechanical. When leveraged
positions get liquidated, the exchange force-sells/buys, pushing price
further against the crowd. This creates a predictable directional move
that LEMON is already positioned for.

---

## Signal Pipeline

### Phase 1: Target Acquisition (every 5 minutes)

Call `discovery_get_top_traders` with filters:
```
time_frame: "WEEKLY"
activity_labels: ["DEGEN"]
consistency: ["CHOPPY"]
limit: 10
```

This returns the top 10 DEGEN/CHOPPY traders by recent activity.

### Phase 2: Vulnerability Scan

For each target trader, call `discovery_get_trader_state` to inspect
their live open positions. Look for the vulnerability trigger:

| Condition | Threshold | Why |
|---|---|---|
| Leverage | >= 10x | Over-leveraged = closer to liquidation |
| ROE | < -10% | Already bleeding = liquidation approaching |
| Position exists | Active, not closed | Still in the trade |

**Both conditions must be true simultaneously.** A degen at 20x leverage
but +5% ROE is winning — don't fade a winner. A trader at 5x and -15%
has room to breathe — liquidation is far away. The sweet spot is high
leverage AND actively losing.

### Phase 3: Conviction Scoring

Not every bleeding degen is worth fading. Score the setup:

| Signal | Points | Description |
|---|---|---|
| Target leverage >= 10x | 2 | Base threshold |
| Target leverage >= 20x | +1 | High leverage = faster cascade |
| Target ROE < -10% | 2 | Base threshold |
| Target ROE < -20% | +1 | Deep in the red = liquidation imminent |
| Multiple degens on same asset/direction | +2 | Cluster = bigger cascade |
| Asset funding rate confirms fade direction | +1 | Structural pressure aligned |
| SM (smart money) aligned with fade direction | +1 | Top traders agree with our side |

**Minimum score: 6 to enter.**

### Phase 4: SM Confirmation Gate

Before entering, check `leaderboard_get_markets` for the fade asset:
- Is smart money positioned in our fade direction?
- Are there 10+ SM traders on the asset?

If SM is actively positioned AGAINST our fade direction (i.e., SM agrees
with the degens), SKIP. Don't fight both degens AND smart money.

### Phase 5: Entry

If score >= 6 and SM gate passes:

```
Asset: [Target's coin]
Direction: OPPOSITE of target's direction
Leverage: 5x (conservative — we're betting on their liquidation, not YOLO-ing ourselves)
Margin: 15% of account value
Order type: FEE_OPTIMIZED_LIMIT
```

**Why 5x leverage:** The fade thesis plays out over minutes to hours. At 5x,
a 3% favorable move = +15% ROE. We don't need 20x — that's what the degens
use, and that's why they blow up.

---

## Exit Management (DSL v1.1.1)

Scanner generates COMPLETE DSL state. Agent writes directly to
`state/dsl-{COIN}.json`.

### Phase 1 (Entry Protection)

| Parameter | Value | Why |
|---|---|---|
| Absolute floor | -15% ROE | At 5x, allows 3% adverse price move |
| Hard timeout | 60 min | If no cascade in 1 hour, thesis is wrong |
| Weak peak cut | 30 min | Peak declining for 30 min = fading |
| Dead weight cut | 15 min | 15 min flat = no cascade happening |
| Consecutive breaches | 3 | Survive single wicks |
| Retrace threshold | 0.20 | 20% retrace from entry peak |

### Phase 2 (Profit Trailing)

| Trigger ROE | Lock % of Peak | Breaches | Note |
|---|---|---|---|
| +10% | 40% | 3 | Initial cascade profits |
| +20% | 55% | 2 | Cascade developing |
| +30% | 70% | 1 | Strong cascade |
| +40% | 80% | 1 | Full liquidation run |
| +60% | 85% | 1 | Extended cascade |

### Stagnation TP

If ROE >= 10% and high water hasn't moved for 30 minutes, take profit.
Cascades are violent and fast — if the move stalls, take what you have.

---

## Risk Management

| Rule | Value |
|---|---|
| Max positions | 2 |
| Max entries/day | 4 |
| Leverage | 5x (fixed) |
| Margin per trade | 15% of account |
| Per-asset cooldown | 180 min |
| Daily loss limit | 10% |
| Consecutive losses | 3 → 45 min cooldown |
| XYZ assets | Banned |
| Max single trade loss | 3% of account (floor at -15% ROE × 15% margin = 2.25%) |

### Anti-Patterns (Hard-Coded)

1. **NEVER fade a winning degen.** ROE must be < -10% before fading.
2. **NEVER fade when SM agrees with the degen.** If smart money is on the same side as the target, the degen might accidentally be right.
3. **NEVER use more than 5x leverage.** We're the patient predator, not another degen.
4. **NEVER re-enter the same asset within 3 hours.** If the first fade didn't work, the thesis was wrong.
5. **Max 1 fade per trader cluster.** If 3 degens are all long BTC, that's one fade signal, not three.

---

## Cron Architecture (2 crons only)

### Cron 1: Scanner (5 min, main session)
```
python3 /data/workspace/skills/lemon-strategy/scripts/lemon-scanner.py
```

### Cron 2: DSL (3 min, isolated session)
```
python3 /data/workspace/skills/dsl-dynamic-stop-loss/scripts/dsl-v5.py --state-dir /data/workspace/skills/lemon-strategy/state
```

**No custom exit engine.** No highwater tracker cron. DSL handles all exits.

---

## Data Sources

| Data | MCP Tool | Purpose |
|---|---|---|
| Degen traders | `discovery_get_top_traders` | Find DEGEN/CHOPPY targets |
| Trader positions | `discovery_get_trader_state` | Check leverage, ROE, direction |
| SM consensus | `leaderboard_get_markets` | Confirmation gate |
| Asset data | `market_get_asset_data` | Funding rate, price context |
| Account state | `strategy_get_clearinghouse_state` | Position tracking |

---

## State Files

```
state/
  dsl-{COIN}.json          # DSL v1.1.1 state per position
  trade-counter.json        # Daily entries, loss tracking, gate
  cooldowns.json            # Per-asset cooldown after exits
  scan-history.json         # Recent degen scans for cluster detection
```

---

## Bootstrap Gate

On EVERY session start, check `config/bootstrap-complete.json`. If missing:
1. Verify Senpi MCP
2. Create scanner cron (5 min, main)
3. Create DSL cron (3 min, isolated)
4. Verify BOTH crons `status: ok`
5. Write `config/bootstrap-complete.json`
6. Send: "🍋 LEMON v1.0 online. Degen Fader scanning for bleeding high-leverage traders. Silence = no vulnerable degens."

---

## Notification Policy

**ONLY alert:** Position OPENED (target trader, their leverage/ROE, our
fade direction, score), Position CLOSED (P&L, close reason, duration),
risk gate triggered, critical error.

**NEVER alert:** Scanner found no vulnerable degens, DSL routine checks,
target trader still alive (not yet triggered), any reasoning about whether
to exit.

---

## Expected Behavior

| Metric | Expected |
|---|---|
| Entries/day | 0-3 (many zero-trade days) |
| Win rate | ~45-55% |
| Avg winner | 2-3x avg loser (cascade runs > small losses) |
| Position duration | 10 min to 2+ hours |
| Hold time on winners | Longer (cascades compound) |

**Most days will have zero trades.** DEGEN/CHOPPY traders at 20x+ leverage
AND -10%+ ROE is a specific, uncommon setup. That's the point — high
conviction entries only.

---

## Why "LEMON"

Because we're squeezing the lemons. 🍋

---

## Package Contents

The complete skill is in `lemon-v1.0.tar.gz`. Extract to `/data/workspace/skills/lemon-strategy/`.

| File | Purpose |
|---|---|
| `SKILL.md` | This document — all rules, architecture, and configuration |
| `README.md` | Short overview |
| `scripts/lemon-scanner.py` | Degen finder + vulnerability scan + conviction scoring + entry signal + DSL state generation |
| `scripts/lemon_config.py` | Config helper (MCP calls, state I/O, cooldowns, trade counter) |
| `config/lemon-config.json` | Wallet, strategy ID, configurable thresholds (agent fills in wallet/strategyId) |

---

## Installation

1. Extract `lemon-v1.0.tar.gz` to `/data/workspace/skills/lemon-strategy/`
2. Create a strategy vault and fund it with $1,000
3. Update `config/lemon-config.json` with the wallet address and strategy ID
4. Create scanner cron (5 min, main): `python3 /data/workspace/skills/lemon-strategy/scripts/lemon-scanner.py`
5. Create DSL cron (3 min, isolated): `python3 /data/workspace/skills/dsl-dynamic-stop-loss/scripts/dsl-v5.py --state-dir /data/workspace/skills/lemon-strategy/state`
6. Verify BOTH crons running with `openclaw crons list`
7. After first position opens, verify DSL state file exists at `state/dsl-{COIN}.json` with wallet address and size fields populated

---

## License

MIT — Built by Senpi (https://senpi.ai).
Source: https://github.com/Senpi-ai/senpi-skills
