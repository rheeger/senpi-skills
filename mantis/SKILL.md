---
name: mantis-strategy
description: >-
  MANTIS v3.0 — Dual-mode emerging movers scanner. All live trading lessons
  applied, plus one experimental tweak: contribution acceleration threshold
  raised from 0.001 to 0.003 and the weak +1 tier (CONTRIB_POSITIVE) eliminated.
  Only genuine SM acceleration earns contribution points. Stalker minScore 7,
  minTotalClimb 8, tighter Phase 1 for low-score entries, consecutive-loss
  streak gate. XYZ banned. Leverage 7-10x. DSL exit managed by plugin runtime via recipe.yaml.
license: MIT
metadata:
  author: jason-goldberg
  version: "3.0"
  platform: senpi
  exchange: hyperliquid
  config_source: mantis-v2-plus-contrib-threshold-experiment
  requires:
    - senpi-trading-runtime
---

# 🦗 MANTIS v3.0 — Dual-Mode Scanner + Contribution Threshold Experiment

Patient. Precise. Only strikes when SM acceleration is real.

---

## ⛔ CRITICAL AGENT RULES — READ BEFORE ANYTHING ELSE

### RULE 1: Install path is `/data/workspace/skills/mantis-strategy/`

The skill MUST be installed to exactly this path.

### RULE 2: MAX 3 POSITIONS — check before EVERY entry

Before opening ANY position, call `strategy_get_clearinghouse_state` and count open positions. If positions >= 3, SKIP.

### RULE 3: Scanner output is AUTHORITATIVE — never override from memory

The scanner is the single source of truth for all trading parameters.

### RULE 4: Verify recipe is installed on every session start

Run `openclaw senpi trading-recipe list`. Recipe must be listed. The position tracker and DSL exit are handled by the plugin runtime.

### RULE 5: Never retry timed-out position creation

If `create_position` times out, check clearinghouse state first.

### RULE 6: Never modify your own configuration

No adjustments to leverage, margin, scoring, or any parameter.

### RULE 7: Record Stalker results for streak tracking

After every Stalker position closes, call `record_stalker_result(tc, is_win)`.

---

## The MANTIS v3.0 Experiment

**Hypothesis:** Fox v1.0's weak Stalker trades often carried the CONTRIB_POSITIVE reason — a +1 score bonus for contribution velocity between 0 and 0.001 per scan. This is technically "positive" but so weak it's effectively noise. A contribution delta of 0.0005 means SM interest grew by 0.05% per scan — statistically indistinguishable from random fluctuation. Meanwhile, the +2 CONTRIB_ACCEL signal (delta > 0.001) correlated with actual winning trades where SM was genuinely building.

**The tweak:** Contribution acceleration threshold raised from 0.001 to 0.003. The +1 tier (CONTRIB_POSITIVE: delta between 0 and threshold) is eliminated entirely. This is the ONLY difference from the base scanner.

**What this changes in scoring:**
- Old: delta 0.0005 → +1 (CONTRIB_POSITIVE). New: delta 0.0005 → +0 (ignored)
- Old: delta 0.0015 → +2 (CONTRIB_ACCEL). New: delta 0.0015 → +0 (below new threshold)
- Old: delta 0.004 → +2 (CONTRIB_ACCEL). New: delta 0.004 → +2 (CONTRIB_ACCEL, passes)

**Expected effect:** Stalker max theoretical score drops from +8 to +7 for assets with weak acceleration. Only assets with strong SM momentum (delta > 0.003) get the +2 contribution bonus. This should eliminate the "barely climbing with barely growing interest" chop trades while preserving entries where SM is genuinely accelerating.

---

## Dual-Mode Entry

### MODE A — STALKER (Accumulation) — Score >= 7
- SM rank climbing steadily over 3+ consecutive scans
- Total climb >= 8 ranks
- Contribution building each scan
- 4H trend aligned
- **v3.0: Contribution acceleration must exceed 0.003 for +2 bonus. No +1 tier.**
- **Streak gate:** 3 consecutive Stalker losses → minScore raised to 9

### MODE B — STRIKER (Explosion) — Score >= 9, min 4 reasons
- FIRST_JUMP or IMMEDIATE_MOVER (10+ rank jump from #25+)
- Rank jump >= 15 OR velocity > 15
- Raw volume >= 1.5x of 6h average
- Unchanged

---

## Exit Management

DSL exit is handled by the plugin runtime via `recipe.yaml`. The `position_tracker` scanner auto-detects position opens/closes on-chain. See `recipe.yaml` for configuration details.

**Entry flow:**
1. Scanner outputs signal
2. Verify positions < 3
3. Verify exchange max leverage >= 7
4. Call `create_position`
5. Send ONE notification: position opened
6. `position_tracker` detects the new position automatically
7. Plugin DSL monitor applies trailing stop-loss protection

**Monitor positions:**
- `openclaw senpi dsl positions` — list all DSL-tracked positions
- `openclaw senpi dsl inspect <ASSET>` — full position details

**On position close:**
8. Call `record_stalker_result(tc, is_win)` if Stalker entry

---

## Recipe Setup

**Step 1:** Set your strategy wallet address in the recipe:
```bash
sed -i 's/${WALLET_ADDRESS}/<STRATEGY_WALLET_ADDRESS>/' /data/workspace/skills/mantis-strategy/recipe.yaml
```
Replace `<STRATEGY_WALLET_ADDRESS>` with the actual wallet address.

**Step 2:** Install the trading recipe:
```bash
openclaw senpi trading-recipe create --path /data/workspace/skills/mantis-strategy/recipe.yaml
```

**Step 3:** Verify:
```bash
openclaw senpi trading-recipe list
```

---

## Bootstrap Gate

On EVERY session start, check `config/bootstrap-complete.json`. If missing:
1. Read the senpi-trading-runtime skill: `cat /data/workspace/skills/senpi-trading-runtime/SKILL.md` — this provides all CLI commands for recipe management and DSL position inspection.
2. Verify Senpi MCP
3. Set wallet in recipe: `sed -i 's/${WALLET_ADDRESS}/ACTUAL_ADDRESS/' /data/workspace/skills/mantis-strategy/recipe.yaml`
4. Install recipe: `openclaw senpi trading-recipe create --path /data/workspace/skills/mantis-strategy/recipe.yaml`
5. Verify recipe installed: `openclaw senpi trading-recipe list`
6. Create scanner cron (90s, main)
7. Write `config/bootstrap-complete.json`
8. Send: "🦗 MANTIS v3.0 online. Contrib threshold 0.003, no weak tier. Silence = no conviction."

If bootstrap exists, still verify recipe and scanner cron on every session start.

---

## Risk Management

| Rule | Value |
|---|---|
| Max positions | 3 |
| Max entries/day | 6 |
| Leverage | 7-10x |
| Daily loss limit | 10% |
| Per-asset cooldown | 2 hours |
| XYZ equities | Banned |
| Contrib accel threshold | 0.003 (experiment, was 0.001) |
| Stalker streak gate | 3 losses → minScore 9 |

---

## Notification Policy

**ONLY alert:** Position OPENED, position CLOSED (P&L + reason), streak gate activated/deactivated, critical error.

**NEVER alert:** Scanner found nothing, any reasoning.

---

## Files

| File | Purpose |
|---|---|
| `scripts/mantis-scanner.py` | Dual-mode scanner with contrib threshold experiment |
| `scripts/mantis_config.py` | Config helper with stalkerResults tracking |
| `config/mantis-config.json` | Config with Mantis v3.0 thresholds |
| `recipe.yaml` | Trading recipe for plugin runtime (DSL exit + position tracker) |

---

## License

MIT — Built by Senpi (https://senpi.ai).
Source: https://github.com/Senpi-ai/senpi-skills
