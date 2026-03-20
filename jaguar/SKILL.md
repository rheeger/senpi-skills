---
name: jaguar-strategy
description: >-
  JAGUAR v1.0 — Three-mode scanner with gen-2 signal intelligence and pyramiding.
  Three entry modes: STALKER (SM accumulation, 3+ scan climb), STRIKER (violent
  first-jump explosion), HUNTER (independent gen-2 signal from momentum events +
  quality traders + velocity divergence). All signals scored with TCS/TRP quality
  tags from Tier 2 momentum events. Rhino-style pyramiding on winning Phase 2
  positions with re-confirmation. Max 7 positions. XYZ banned. Leverage 7-10x.
  DSL state template in scanner output. Every lesson from 30 agents baked in.
license: MIT
metadata:
  author: jason-goldberg
  version: "1.0"
  platform: senpi
  exchange: hyperliquid
  config_source: 30-agent-arena-gen2-signals-pyramiding
---

# 🐆 JAGUAR v1.0 — Three-Mode Scanner + Gen-2 Intelligence + Pyramiding

Land. Water. Trees. Three domains. One predator. Every lesson from 30 agents and $26K capital baked into the code.

---

## ⛔ CRITICAL AGENT RULES — READ BEFORE ANYTHING ELSE

These rules exist because previous agents violated them and caused real losses. Every rule below is non-negotiable.

### RULE 1: Install path is `/data/workspace/skills/jaguar-strategy/`

The skill MUST be installed to exactly this path. A prior agent installed to `~/.openclaw/skills/` which broke scanner state tracking and led to 22 open positions. If you are reading this file from any other path, STOP and reinstall.

### RULE 2: MAX 7 POSITIONS — check before EVERY entry

Before opening ANY position, you MUST call `strategy_get_clearinghouse_state` and count open positions. If positions >= 7, SKIP. No exceptions. No "just one more." A prior agent opened 22 positions because it ignored the maxPositions constraint.

The scanner outputs `currentPositions` and `constraints.maxPositions` in every scan. Verify these match what you see from clearinghouse state.

### RULE 3: Scanner output is AUTHORITATIVE — never override from memory

If the scanner says `minLeverage: 7`, you use 7. Not 5 from your MEMORY.md. Not 3 from a prior conversation. A prior agent entered at 3x leverage because its memory overrode the scanner. The scanner is the single source of truth for all trading parameters.

Parameters you MUST NOT override: leverage, margin, maxPositions, dailyLossLimit, cooldown times, DSL tiers, conviction tiers, stagnation TP, quality tag weights. All of these are HARDCODED in the scanner Python code.

### RULE 4: Verify BOTH crons on every session start

On every session start (including after sleep/wake), run `openclaw crons list` and verify:
- Scanner cron: status `ok`, running every 90s
- DSL cron: status `ok`, running every 3 min

If either is missing or not `ok`, recreate it. A prior agent had 22 open positions with NO DSL cron running — no trailing stops, no Phase 1 cuts, nothing.

### RULE 5: Write dslState directly — do not construct manually

When opening a position, the scanner provides a `dslState` block for each signal. Write this DIRECTLY to `state/{TOKEN}.json` via `json.dumps`. Do not modify fields. Do not reconstruct. Do not populate from memory. A prior agent wrote margin amount into the size field and a position ran naked with no stop-loss, losing $306.

### RULE 6: Never retry timed-out position creation

If `create_position` times out, do NOT retry. Check `strategy_get_clearinghouse_state` to see if the position exists. If it does, create the DSL state file and move on. If it doesn't, skip and wait for the next scan cycle.

### RULE 7: Never modify your own configuration

Do not adjust leverage, margin, entry caps, scoring thresholds, DSL parameters, or any other configuration parameter. Every agent that self-modified during losing streaks made things worse. Zero exceptions across 30 agents.

---

## What JAGUAR Does

### Three Entry Modes

**MODE A — STALKER (Accumulation) — Score >= 6**
Smart money rank climbing steadily over 3+ consecutive scans with contribution building each scan. 4H trend aligned. This is the ZEC/SILVER pattern — SM quietly accumulating before the explosion.

**MODE B — STRIKER (Explosion) — Score >= 9, min 4 reasons**
Violent FIRST_JUMP or IMMEDIATE_MOVER (10+ rank jump from #25+). Rank jump >= 15 OR contribution velocity > 15. Raw volume >= 1.5x of 6h average.

**MODE C — HUNTER (Gen-2 Independent) — Score >= 8**
Fires from gen-2 data alone — doesn't need Stalker rank climbing or Striker rank jumps. Pipeline: Tier 2 momentum event ($5.5M+) with non-blocked traders → asset on SM leaderboard (top 50) → contribution velocity aligned → volume confirmed. This fuses three specialized scanner concepts into one mode.

**PYRAMID — Position Scaling — Phase 2 + re-confirmation**
Adds to existing winning positions (ROE > 7%) when the thesis is re-confirmed: asset still in SM leaderboard top 35 OR fresh momentum event from non-blocked traders. Conservative: 50% of original margin, max 1 per position, account margin capped at 60%.

### Gen-2 Confirmation Layer (on ALL modes)

Every signal is cross-referenced against Tier 2 momentum events with TCS/TRP quality tags.

**Score modifiers:**

| Tag | Value | Score Delta |
|---|---|---|
| TCS ELITE | Consistent winner, no negative weeks | +2 |
| TCS RELIABLE | Mostly consistent | +1 |
| TCS STREAKY | Mixed results | +0 |
| TCS CHOPPY | Unreliable | -2 |
| TRP SNIPER | High risk-reward precision | +1 |
| TRP AGGRESSIVE | Big positions, big swings | +1 |
| TRP BALANCED | Average | +0 |
| TRP CONSERVATIVE | Small positions | -1 |
| Concentration > 0.7 | Gains focused in this asset | +1 |
| Velocity > 5%, aligned | SM moving before price | +1 |
| Velocity-price divergence | SM moving, price hasn't caught up | +1 |
| Velocity retreating | SM leaving the trade | -1 |

**Hard gate:** TCS CHOPPY + TRP CONSERVATIVE → signal BLOCKED regardless of score.

---

## MANDATORY: DSL High Water Mode

**JAGUAR MUST use DSL High Water Mode. This is not optional.**

Spec: https://github.com/Senpi-ai/senpi-skills/blob/main/dsl-dynamic-stop-loss/dsl-high-water-spec%201.0.md

```json
{
  "lockMode": "pct_of_high_water",
  "phase2TriggerRoe": 7,
  "tiers": [
    {"triggerPct": 7,  "lockHwPct": 40, "consecutiveBreachesRequired": 3},
    {"triggerPct": 12, "lockHwPct": 55, "consecutiveBreachesRequired": 2},
    {"triggerPct": 15, "lockHwPct": 75, "consecutiveBreachesRequired": 2},
    {"triggerPct": 20, "lockHwPct": 85, "consecutiveBreachesRequired": 1}
  ]
}
```

### Phase 1 (Conviction-Scaled)

| Score | Absolute Floor | Hard Timeout | Weak Peak | Dead Weight |
|---|---|---|---|---|
| 6-7 (Stalker) | -20% ROE | 30 min | 15 min | 10 min |
| 8-9 (Hunter) | -25% ROE | 45 min | 20 min | 15 min |
| 10+ (Striker) | -30% ROE | 60 min | 30 min | 20 min |

### Pyramid Phase 1 (Tighter — base position already proven)

| Absolute Floor | Hard Timeout | Dead Weight |
|---|---|---|
| -15% ROE | 20 min | 8 min |

### Stagnation TP (MANDATORY — do not remove)

If ROE >= 10% and high water hasn't moved for 45 minutes, take profit. This is not optional.

---

## Scanner Output — DSL State Template

Each signal in `combined` and `pyramidSignals` includes a `dslState` block.

**The agent MUST write this block directly as the DSL state file after opening a position.**

**Entry flow for new positions:**
1. Scanner outputs signal with `dslState` block
2. Verify `currentPositions < constraints.maxPositions` (check clearinghouse state)
3. Verify exchange max leverage >= `constraints.minLeverage` for this asset
4. Call `create_position` with coin, direction, leverage, margin
5. Write `state/{TOKEN}.json` with the exact contents of `signal.dslState`, plus `entryPrice`, `leverage`, and `createdAt`
6. Send ONE notification: position opened (mode, asset, direction, score, top reasons)
7. DSL cron picks up the state file and manages the position

**Entry flow for pyramids:**
1. Scanner outputs pyramid signal with `dslState` block
2. Verify account margin < 60% (check `totalMarginPct` in scanner output)
3. Call `edit_position` to increase size (add `pyramidMargin` amount)
4. Write `state/{TOKEN}-pyramid.json` with the pyramid `dslState`
5. Record pyramid via scanner state tracking
6. Send ONE notification: pyramid added

**If the DSL state file is not created, the position is NAKED — no stop-loss protection.**

---

## Cron Setup

**EXACT commands — copy-paste these. Do not modify.**

Scanner cron (90 seconds, main session):
```
python3 /data/workspace/skills/jaguar-strategy/scripts/jaguar-scanner.py
```

DSL cron (3 minutes, isolated session):
```
python3 /data/workspace/skills/dsl-dynamic-stop-loss/scripts/dsl-v5.py --state-dir /data/workspace/skills/jaguar-strategy/state
```

**NOT `npx skills exec`. NOT any other wrapper.**

---

## Bootstrap Gate

On EVERY session start, check `config/bootstrap-complete.json`. If missing:

1. Verify Senpi MCP connection
2. Create scanner cron (90s, main session):
   `python3 /data/workspace/skills/jaguar-strategy/scripts/jaguar-scanner.py`
3. Create DSL cron (3 min, isolated session):
   `python3 /data/workspace/skills/dsl-dynamic-stop-loss/scripts/dsl-v5.py --state-dir /data/workspace/skills/jaguar-strategy/state`
4. Verify BOTH crons show `status: ok` via `openclaw crons list`
5. Write `config/bootstrap-complete.json` with timestamp
6. Send: "🐆 JAGUAR v1.0 online. Three-mode scanner + gen-2 intelligence + pyramiding active. All gates enforced in code. Silence = no conviction."

If `config/bootstrap-complete.json` EXISTS, still verify both crons are running (`openclaw crons list`). If either is missing or not `ok`, recreate and notify.

---

## Risk Management

| Rule | Value | Why |
|---|---|---|
| Max positions | 7 | Room for all three modes to fire |
| Max entries/day | 10 | Scaled up with position limit |
| Leverage | 7-10x | Sub-7x can't overcome fees; 15x blows up |
| Daily loss limit | 10% | Proven across 30 agents |
| Per-asset cooldown | 2 hours | Prevents double-entry on same asset |
| Stagnation TP | 10% ROE / 45 min | Captures peaks that flatline |
| XYZ equities | Banned | Net negative across every agent |
| Pyramid max per position | 1 | Conservative scaling |
| Pyramid margin | 50% of original | Don't double down at peak |
| Pyramid max account margin | 60% | Never over-leverage the account |

---

## Notification Policy

**ONLY alert:** Position OPENED (mode, asset, direction, score, top 3 reasons), position CLOSED (DSL or Phase 1 with reason and P&L), PYRAMID added (asset, margin, ROE at add), risk guardian triggered, critical error.

**NEVER alert:** Scanner ran with no signals, signals filtered by gen-2 gates, momentum events processed, DSL routine check, system status, any reasoning about whether to enter, any consideration of overriding parameters.

**Standing rule:** Do not modify config, scoring thresholds, DSL tiers, leverage limits, quality tag weights, or entry parameters without explicit approval from Jason. Silence means working.

---

## Diagnostic Checklist (for reviewing this agent)

When diagnosing issues, check in this order:

1. Is the skill installed at `/data/workspace/skills/jaguar-strategy/`?
2. Are BOTH crons running? (`openclaw crons list` → scanner + DSL both `status: ok`)
3. Are DSL field names correct? (`phase1MaxMinutes`, `deadWeightCutMin`)
4. Is `highWaterPrice: null`? (NOT 0)
5. Is `consecutiveBreachesRequired: 3` in Phase 1?
6. Is `absoluteFloorRoe` dynamic? (NOT a static dollar price)
7. Does scanner margin match actual position margin? (Hallucination check)
8. Is the agent modifying its own config? (Any "I updated" = red flag)
9. How many positions are open vs MAX_POSITIONS (7)?
10. Are pyramid state files present for pyramided positions?

---

## Files

| File | Purpose |
|---|---|
| `scripts/jaguar-scanner.py` | Three-mode scanner with gen-2 integration + pyramiding |
| `scripts/jaguar_config.py` | Self-contained config helper with pyramid tracker |
| `config/jaguar-config.json` | Base configuration with all three mode settings |

---

## License

MIT — Built by Senpi (https://senpi.ai).
Source: https://github.com/Senpi-ai/senpi-skills
