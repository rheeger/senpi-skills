---
name: bald-eagle-strategy
description: >-
  BALD EAGLE v3.0 — XYZ Alpha Hunter. Trades high-liquidity XYZ assets on
  Hyperliquid: commodities (GOLD, SILVER, CL, BRENTOIL), indices (SP500, XYZ100),
  and select equities (TSLA, NVDA). Spread gate rejects illiquid assets.
  Leverage capped at 7x (v1.0 used 20x and got liquidated).
  DSL manages all exits. No thesis exit.
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

# 🦅 BALD EAGLE v3.0 — XYZ Alpha Hunter

The only Senpi agent trading commodities, indices, and equities on Hyperliquid.

---

## ⛔ CRITICAL AGENT RULES

### RULE 1: Install path is `/data/workspace/skills/bald-eagle-strategy/`

### RULE 2: THE SCANNER DOES NOT EXIT POSITIONS

### RULE 3: SPREAD GATE IS THE FILTER — NOT A WHITELIST

All 54 XYZ assets are eligible. The live spread gate (> 0.1% = rejected)
automatically filters out illiquid garbage. No static whitelist needed.
SNDK is the only hard ban.

### RULE 4: MAX 3 POSITIONS at a time

### RULE 5: Verify recipe is installed on every session start

Run `openclaw senpi trading-recipe list`. Recipe must be listed. The position tracker and DSL exit are handled by the plugin runtime.

### RULE 6: Never retry timed-out position creation

If `create_position` times out, check clearinghouse state. If position exists, the position tracker will pick it up automatically. If not, wait for next scan.

### RULE 7: Never modify parameters. Never increase leverage above 7x.

### RULE 8: 120-minute per-asset cooldown

---

## v1.0 Post-Mortem

- 6 trades, 5 had broken DSL (state files in wrong directory)
- CL LONG at 20x: LIQUIDATED at -56.4% ROE, ran 3.7 hours orphaned
- GOLD SHORT at 20x: ran 15 hours unprotected, closed manually at -1.4%
- BRENTOIL LONG at 20x: ran 3.2 hours unprotected, closed manually at -21.3%
- 86% of losses ($246 of $286) came from DSL infrastructure failure

## What Changed

| v1.0 | v2.0 |
|---|---|
| No asset whitelist | GOLD, SILVER, CL, BRENTOIL, SP500, XYZ100, TSLA, NVDA |
| No spread check | Spread gate: rejects > 0.1% live spread |
| 20x leverage | 7x leverage |
| DSL state missing wallet | Wallet + strategyId + size included |
| No entry limits | 3 entries/day max |
| Thesis exit active | Removed — DSL manages all exits |

---

## Whitelisted Assets (Live Data)

| Asset | Type | 24H Volume | Spread | Max Lev |
|---|---|---|---|---|
| SILVER | Commodity | $487M | 0.007% | 25x |
| CL | Commodity | $375M | 0.043% | 20x |
| BRENTOIL | Commodity | $285M | 0.040% | 20x |
| SP500 | Index | $175M | TBD | 50x |
| XYZ100 | Index | $158M | TBD | 30x |
| GOLD | Commodity | $101M | 0.002% | 25x |
| TSLA | Equity | $17M | 0.034% | 10x |
| NVDA | Equity | $15M | 0.069% | 20x |

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
sed -i 's/${WALLET_ADDRESS}/<STRATEGY_WALLET_ADDRESS>/' /data/workspace/skills/bald-eagle-strategy/recipe.yaml
```
Replace `<STRATEGY_WALLET_ADDRESS>` with the actual wallet address.

**Step 2:** Set telegram chat ID for notifications:
```bash
sed -i 's/${TELEGRAM_CHAT_ID}/<CHAT_ID>/' /data/workspace/skills/bald-eagle-strategy/recipe.yaml
```
Replace `<CHAT_ID>` with the actual Telegram chat ID.

**Step 3:** Install the trading recipe:
```bash
openclaw senpi trading-recipe create --path /data/workspace/skills/bald-eagle-strategy/recipe.yaml
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
3. Set wallet in recipe: `sed -i 's/${WALLET_ADDRESS}/ACTUAL_ADDRESS/' /data/workspace/skills/bald-eagle-strategy/recipe.yaml`
4. Set telegram in recipe: `sed -i 's/${TELEGRAM_CHAT_ID}/CHAT_ID/' /data/workspace/skills/bald-eagle-strategy/recipe.yaml`
5. Install recipe: `openclaw senpi trading-recipe create --path /data/workspace/skills/bald-eagle-strategy/recipe.yaml`
6. Verify recipe installed: `openclaw senpi trading-recipe list`
7. Create scanner cron (5 min, main)
8. Write `config/bootstrap-complete.json`
9. Send: "🦅 BALD EAGLE v3.0 online. XYZ Alpha Hunter with spread gate. DSL managed by plugin runtime. Silence = no alpha."

If bootstrap exists, still verify recipe and scanner cron on every session start.

---

## Risk

| Rule | Value |
|---|---|
| Max positions | 3 |
| Max entries/day | 6 |
| Leverage | 7x (capped) |
| Spread gate | > 0.1% = rejected |
| Per-asset cooldown | 90 min |
| Daily loss limit | 10% |
| SNDK | Banned |

---

## Files

| File | Purpose |
|---|---|
| `scripts/eagle-scanner.py` | XYZ SM scanner with spread gate + conviction scoring |
| `scripts/eagle_config.py` | Config helper (MCP, state, market hours, cooldowns) |
| `config/bald-eagle-config.json` | Wallet, strategy ID |
| `recipe.yaml` | Trading recipe for plugin runtime (DSL exit + position tracker) |

---

## License

MIT — Built by Senpi (https://senpi.ai).
