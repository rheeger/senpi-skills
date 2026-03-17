---
name: orca-strategy
description: >-
  ORCA v1.1.1 — Hardened dual-mode emerging movers scanner. Every lesson from
  5+ days of live trading across 22 agents baked into the code. v1.1 adds
  the DSL state template directly in scanner output — eliminating the
  dsl-profile.json override bugs that broke Fox, Grizzly, Jackal, and every
  Wolf-based agent. XYZ equities banned at scan level. Leverage 7-10x enforced.
  Stagnation TP mandatory. 10% daily loss limit. 2-hour per-asset cooldown.
  Conviction-scaled Phase 1 timing per-signal. The agent cannot override any
  of these — they are in the scanner, not instructions.
license: MIT
metadata:
  author: jason-goldberg
  version: "1.1.1"
  platform: senpi
  exchange: hyperliquid
  based_on: vixen-v1.0
  config_source: fox-winning-config-day5-plus-dsl-audit
---

# 🐋 ORCA v1.1.1 — Hardened Dual-Mode Scanner

Fox's brain. Vixen's architecture. Every lesson from 22 agents locked into the code.

## What v1.1 Fixes (DSL Audit)

The audit across all 22 agents revealed that every agent except Orca v1.0 had broken DSL configs. The root causes:

1. **`consecutiveBreachesRequired: 1` in Phase 1** — meant a single price wick killed the position. Fox's entire losing streak traced to this. Fix: hardcoded to 3.
2. **`deadWeightCutMinutes: 0`** — positions that never went positive sat for 30+ minutes bleeding. COPPER sat at 0% ROE for 36 hours on Fox. Fix: hardcoded to 10/15/20 by conviction.
3. **`stagnationTp` stripped by wolf_config.py builder** — the function that merges configs silently dropped stagnation TP and conviction tiers. Dire Wolf, Jackal, and every Wolf-based agent was affected. Fix: DSL state template is now in the scanner output, bypassing all builders.
4. **dsl-v5.py reads top-level Phase 1 values, not per-tier** — even when conviction tiers were present, the DSL engine read the top-level `deadWeightCutMinutes: 0` instead. Fix: scanner now sets the correct top-level values per-signal based on score.

**v1.1 solution:** The scanner outputs a complete `dslState` block for each signal. The agent writes this directly as the state file. No merging with dsl-profile.json. No wolf_config.py builder. No dynamic generation. The scanner is the single source of truth.

## Hardcoded Lessons (in the code, not instructions)

| Lesson Source | What Happened | Gate in ORCA |
|---|---|---|
| Fox SNDK -$57 | XYZ equities are noise | `xyz:` filtered at scan parse level |
| Dire Wolf 25x blowup | Agent raised leverage after losses | Leverage capped 7-10x in scanner output |
| Vixen daily loss 25% | Agent raised limit, bled 2.5x more | 10% daily loss in output constraints |
| PAXG double-entry | Agent re-entered after Phase 1 cut | 2-hour per-asset cooldown enforced |
| Mantis removed stagnation TP | Positions peaked then reversed to zero | Stagnation TP mandatory in output constraints |
| Ghost Fox 740 trades | More trades = more churn = more fees | Max 3 positions, 6 entries/day |

## Dual-Mode Entry (Same as Vixen/Fox)

### MODE A — STALKER (Accumulation)
- SM rank climbing steadily over 3+ consecutive scans
- Contribution building each scan
- 4H trend aligned
- Score >= 6

### MODE B — STRIKER (Explosion)
- FIRST_JUMP or IMMEDIATE_MOVER (10+ rank jump from #25+)
- Rank jump >= 15 OR velocity > 15
- Raw volume >= 1.5x of 6h average
- Score >= 9, minimum 4 reasons

## MANDATORY: DSL High Water Mode

**ORCA MUST use DSL High Water Mode. This is not optional.**

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
| 8-9 | -25% ROE | 45 min | 20 min | 15 min |
| 10+ (Striker) | -30% ROE | 60 min | 30 min | 20 min |

### Stagnation TP (MANDATORY — do not remove)

If ROE >= 10% and high water hasn't moved for 45 minutes, take profit. Fox has this. Mantis removed it and underperformed. This is not optional.

## Scanner Output — DSL State Template (v1.1)

Each signal in `combined` includes a `dslState` block. **The agent MUST write this block directly as the DSL state file after opening a position.** Do not merge with dsl-profile.json. Do not use wolf_config.py. Do not generate your own DSL config.

The `dslState` includes:
- `phase1.consecutiveBreachesRequired: 3` (NOT 1 — Fox's biggest bug)
- `phase1.deadWeightCutMinutes` set per-score (10/15/20 — NOT 0)
- `phase1.hardTimeoutMinutes` set per-score (30/45/60)
- `phase1.weakPeakCutMinutes` set per-score (15/20/30)
- `stagnationTp: {"enabled": true, "roeMin": 10, "hwStaleMin": 45}`
- Full tier table with correct per-tier breaches (3/2/2/1)

**Entry flow:**
1. Scanner outputs signal with `dslState` block
2. Agent calls `strategy_create_position` with coin, direction, leverage, margin
3. Agent writes `state/{TOKEN}.json` with the exact contents of `signal.dslState`, plus `entryPrice`, `leverage`, and `createdAt`
4. Agent sends ONE notification: position opened
5. DSL cron (3 min) picks up the state file and manages the position

**If step 3 is skipped, the position is NAKED — no stop loss protection.**

## Scanner Output Constraints

The scanner includes a `constraints` block in every output that the agent MUST respect:

```json
{
  "constraints": {
    "minLeverage": 7,
    "maxLeverage": 10,
    "maxPositions": 3,
    "maxDailyLossPct": 10,
    "xyzBanned": true,
    "assetCooldownMinutes": 120,
    "stagnationTp": {"enabled": true, "roeMin": 10, "hwStaleMin": 45},
    "dslTiers": [
      {"triggerPct": 7,  "lockHwPct": 40, "consecutiveBreachesRequired": 3},
      {"triggerPct": 12, "lockHwPct": 55, "consecutiveBreachesRequired": 2},
      {"triggerPct": 15, "lockHwPct": 75, "consecutiveBreachesRequired": 2},
      {"triggerPct": 20, "lockHwPct": 85, "consecutiveBreachesRequired": 1}
    ]
  }
}
```

These are hardcoded constants in the scanner Python code. They cannot be changed via config.

## Risk Management

| Rule | Value | Why |
|---|---|---|
| Max positions | 3 | Concentration > diversification |
| Max entries/day | 6 | Fewer trades wins |
| Leverage | 7-10x | Sub-7x can't overcome fees; 15x blows up |
| Daily loss limit | 10% | Vixen at 25% bled 2.5x more |
| Per-asset cooldown | 2 hours | PAXG double-entry lesson |
| Stagnation TP | 10% ROE / 45 min | Captures peaks that flatline |
| XYZ equities | Banned | Net negative across every agent that traded them |

## Cron Architecture

| Cron | Interval | Session | Purpose |
|---|---|---|---|
| Scanner | 90s | main | Dual-mode emerging movers detection |
| DSL v5 | 3 min | isolated | High Water Mode trailing stops |

## Notification Policy

**ONLY alert:** Position OPENED (mode, asset, direction, score, reasons), position CLOSED (DSL or Phase 1 with reason), risk guardian triggered, critical error.

**NEVER alert:** Scanner ran with no signals, signals filtered, DSL routine check, system status, any reasoning.

**Standing rule:** Do not modify config, scoring thresholds, DSL tiers, leverage limits, or entry parameters without explicit approval from Jason. Silence means working.

## Bootstrap Gate

On EVERY session, check `config/bootstrap-complete.json`. If missing:
1. Verify Senpi MCP
2. Create scanner cron (90s, main) and DSL cron (3 min, isolated)
3. Write `config/bootstrap-complete.json`
4. Send: "🐋 ORCA v1.0 is online. Hardened dual-mode scanner active. All gates enforced in code. Silence = no conviction."

## Files

| File | Purpose |
|---|---|
| `scripts/orca-scanner.py` | Dual-mode scanner with hardcoded gates |
| `scripts/orca_config.py` | Self-contained config helper |
| `config/orca-config.json` | Fox's exact winning configuration |

## License

MIT — Built by Senpi (https://senpi.ai).
Source: https://github.com/Senpi-ai/senpi-skills
