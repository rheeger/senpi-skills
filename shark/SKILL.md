---
name: shark
description: >-
  SHARK v2.0 — SM Conviction + Liquidation Cascade Hunter. Consolidated from
  v1.0's 8-cron pipeline into a single scanner. 4-gate entry: SM concentration
  (30+ traders, 5%+) → top 5 trader alignment → price momentum → funding
  structure. Score 8+ to enter. DSL manages all exits. No thesis exit.
license: MIT
metadata:
  author: jason-goldberg
  version: "2.0"
  platform: senpi
  exchange: hyperliquid
---

# 🦈 SHARK v2.0 — SM Conviction + Liquidation Cascade Hunter

Four gates. One scanner. DSL manages exits.

---

## ⛔ CRITICAL AGENT RULES

### RULE 1: Install path is `/data/workspace/skills/shark/`

### RULE 2: THE SCANNER DOES NOT EXIT POSITIONS

When the scanner sees an active position, it outputs NO_REPLY. DSL is the ONLY exit mechanism. v1.0 lost -4.6% partly because the scanner kept cycling positions rapidly, generating $144/day in fees. v2.0 lets positions run until DSL trails or cuts them.

### RULE 3: MAX 2 POSITIONS at a time

### RULE 4: Scanner output is AUTHORITATIVE

### RULE 5: Write dslState directly — include wallet address

### RULE 6: Verify BOTH crons on every session start

### RULE 7: Never modify parameters

### RULE 8: 120-minute per-asset cooldown

---

## What Changed From v1.0

| v1.0 | v2.0 |
|---|---|
| 10 scripts, 8 crons | 1 scanner + DSL + risk (3 crons) |
| Pipeline: mapper → proximity → entry | Single 4-gate scan |
| Thesis exit active | Thesis exit REMOVED |
| No DSL state generation | Full DSL v1.1.1 state with wallet |
| Crons kept dying silently | Fewer moving parts = more reliable |
| 68 fills, -4.6% | Fewer trades, higher conviction |

---

## The 4 Gates

Every candidate must pass ALL 4 gates to enter:

| Gate | Check | Threshold |
|---|---|---|
| 1. SM Concentration | leaderboard_get_markets | 5%+ gain share, 30+ traders |
| 2. Top 5 Alignment | leaderboard_get_top → trader positions | 2+ of top 5 in same direction |
| 3. Price Momentum | 4H and/or 1H price change aligned | At least one timeframe confirming |
| 4. Funding Structure | Funding rate confirming directional pressure | Funding aligned or neutral |

**Scoring:** SM concentration (0-3 pts) + top alignment (0-3 pts) + momentum (0-2 pts) + contribution acceleration (0-1 pts) + funding (0-1 pts). Score 8+ to enter.

---

## DSL Configuration

| Parameter | Value | Why |
|---|---|---|
| Phase 1 floor | -15% ROE | At 7x, ~2.14% adverse price move |
| Phase 1 timeout | 60 min | Cascades are fast — if nothing in 1hr, wrong |
| Dead weight cut | 15 min | 15 min flat = no cascade happening |
| Weak peak cut | 30 min | Peak declining for 30 min = fading |
| Phase 2 trigger | 8% ROE | Start trailing at +8% |
| Consecutive breaches | 3 | Survive single wicks |

Trailing tiers: 5%/20%, 10%/40%, 20%/55%, 30%/65%, 40%/75%, 60%/80%, 80%/85%, 100%/90%.

---

## Cron Setup (3 crons only)

Scanner (5 min, main):
```
python3 /data/workspace/skills/shark/scripts/shark-scanner.py
```

DSL (3 min, isolated):
```
python3 /data/workspace/skills/dsl-dynamic-stop-loss/scripts/dsl-v5.py --state-dir /data/workspace/skills/shark/state
```

Risk (optional, 10 min, isolated):
```
python3 /data/workspace/skills/shark/scripts/shark-health.py
```

---

## Risk

| Rule | Value |
|---|---|
| Max positions | 2 |
| Max entries/day | 4 |
| Leverage | 7x |
| Per-asset cooldown | 120 min |
| Daily loss limit | 12% |
| Consecutive losses | 3 → 45 min cooldown |
| XYZ | Banned |

---

## Expected Behavior

| Metric | Expected |
|---|---|
| Entries/day | 0-3 (many zero-trade days) |
| Win rate | ~50% |
| Avg winner | 2-3x avg loser |
| Position duration | 15 min to 6+ hours |

---

## License

MIT — Built by Senpi (https://senpi.ai).
