---
name: jaguar-strategy
description: >-
  JAGUAR v3.0 — Striker-Only. Stalker and Hunter removed. Pyramiding removed.
  v1.0 lost -29.3% across 5 trades. 4 of 5 had broken DSL (missing size field
  in state file). v2.0 fixes DSL state generation with wallet+size fields,
  reduces leverage to 7x, and focuses exclusively on STRIKER signals (violent
  FIRST_JUMP explosions, score 9+, volume 1.5x).
  DSL exit managed by plugin runtime via recipe.yaml.
license: MIT
metadata:
  author: jason-goldberg
  version: "3.0"
  platform: senpi
  exchange: hyperliquid
  requires:
    - senpi-trading-runtime
---

# 🐆 JAGUAR v3.0 — Striker-Only

Violent explosions only. DSL manages exits.

---

## ⛔ CRITICAL AGENT RULES

### RULE 1: Install path is `/data/workspace/skills/jaguar-strategy/`

### RULE 2: THE SCANNER DOES NOT EXIT POSITIONS

### RULE 3: MAX 2 POSITIONS at a time

### RULE 4: Scanner output is AUTHORITATIVE

### RULE 5: Verify recipe is installed on every session start

Run `openclaw senpi trading-recipe list`. Recipe must be listed. The position tracker and DSL exit are handled by the plugin runtime.

### RULE 6: Never retry timed-out position creation

If `create_position` times out, check clearinghouse state. If position exists, the position tracker will pick it up automatically. If not, wait for next scan.

### RULE 7: Never modify parameters

### RULE 8: 120-minute per-asset cooldown

---

## What Changed From v1.0

| v1.0 | v2.0 |
|---|---|
| Stalker + Striker + Hunter (3 modes) | **Striker only** |
| Pyramiding enabled | **Removed** |
| DSL state missing wallet + size | **Both included** |
| Leverage 10x | **7x** |
| -29.3% ROE, 4/5 DSL failures | Clean architecture |

---

## v1.0 Post-Mortem

- ZEC score 6 (Stalker): -$97, ran 28 hours with no DSL
- WLD score 6 (Stalker): +$5, ran 28 hours with no DSL
- ADA score 7 (Stalker): -$3, ran 28 hours with no DSL
- HYPE score 11 (Striker): -$35, DSL worked correctly (clean floor hit)
- SOL score 10 (Striker): -$138, ran 10 hours, DSL crashed on missing 'size'

The ONLY trade with working DSL (HYPE) lost $35 instead of $138. With DSL, losses are bounded. Without DSL, they compound until manual intervention.

---

## Exit Management

DSL exit is handled by the plugin runtime via `recipe.yaml`. The `position_tracker` scanner auto-detects position opens/closes on-chain. See `recipe.yaml` for configuration details.

**Monitor positions:**
- `openclaw senpi dsl positions` — list all DSL-tracked positions
- `openclaw senpi dsl inspect <ASSET>` — full position details

---

## Recipe Setup

**Step 1:** Set your strategy wallet address in the recipe:
```bash
sed -i 's/${WALLET_ADDRESS}/<STRATEGY_WALLET_ADDRESS>/' /data/workspace/skills/jaguar-strategy/recipe.yaml
```
Replace `<STRATEGY_WALLET_ADDRESS>` with the actual wallet address.

**Step 2:** Set telegram chat ID for notifications:
```bash
sed -i 's/${TELEGRAM_CHAT_ID}/<CHAT_ID>/' /data/workspace/skills/jaguar-strategy/recipe.yaml
```
Replace `<CHAT_ID>` with the actual Telegram chat ID.

**Step 3:** Install the trading recipe:
```bash
openclaw senpi trading-recipe create --path /data/workspace/skills/jaguar-strategy/recipe.yaml
```

**Step 4:** Verify:
```bash
openclaw senpi trading-recipe list
```

---

## Bootstrap Gate

On EVERY session start, check `config/bootstrap-complete.json`. If missing:
1. Read the senpi-trading-runtime skill: `cat /data/workspace/skills/senpi-trading-runtime/SKILL.md` — this provides all CLI commands for recipe management and DSL position inspection.
2. Verify Senpi MCP
3. Set wallet in recipe: `sed -i 's/${WALLET_ADDRESS}/ACTUAL_ADDRESS/' /data/workspace/skills/jaguar-strategy/recipe.yaml`
4. Set telegram in recipe: `sed -i 's/${TELEGRAM_CHAT_ID}/CHAT_ID/' /data/workspace/skills/jaguar-strategy/recipe.yaml`
5. Install recipe: `openclaw senpi trading-recipe create --path /data/workspace/skills/jaguar-strategy/recipe.yaml`
6. Verify recipe installed: `openclaw senpi trading-recipe list`
7. Remove old DSL cron (if upgrading): run `openclaw crons list`, delete any cron containing `dsl-v5.py` via `openclaw crons delete <id>`
8. Create scanner cron (3 min, main)
9. Write `config/bootstrap-complete.json`
10. Send: "🐆 JAGUAR v3.0 online. Striker-only scanner. DSL managed by plugin runtime. Silence = no explosions."

If bootstrap exists, still verify recipe and scanner cron on every session start.

---

## License

MIT — Built by Senpi (https://senpi.ai).
