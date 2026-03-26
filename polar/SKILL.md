---
name: polar-strategy
description: >-
  POLAR v1.0 — ETH alpha hunter with position lifecycle. Single asset, every signal
  (SM, funding, OI, 4TF trend, volume, BTC correlation). Three-mode lifecycle:
  HUNTING (scan for entry) / RIDING (DSL trails) / STALKING (watch for reload on dip).
  After DSL takes profit, watches for fresh momentum impulse while confirming macro thesis
  is intact. If thesis dies, resets. If dip reloads, re-enters.
  DSL exit managed by plugin runtime via recipe.yaml.
license: MIT
metadata:
  author: jason-goldberg
  version: "1.0"
  platform: senpi
  exchange: hyperliquid
  base_skill: grizzly-v2.0
  requires:
    - senpi-trading-runtime
---

# POLAR v1.0 — ETH Alpha Hunter with Position Lifecycle

One asset. Every signal. Maximum conviction. Reload-on-dip.

POLAR stares at ETH and nothing else. Every signal source available — smart money positioning, funding rate, open interest, 4-timeframe trend structure, volume, BTC correlation — feeds into a single thesis: is there a high-conviction ETH trade right now?

Based on GRIZZLY v2.0's three-mode lifecycle, adapted for ETH's volatility profile.

---

## CRITICAL AGENT RULES — READ BEFORE ANYTHING ELSE

### RULE 1: Verify recipe is installed on every session start

Run `openclaw senpi trading-recipe list`. Recipe must be listed. The position tracker and DSL exit are handled by the plugin runtime.

### RULE 2: MAX 1 POSITION — check before EVERY entry

Before opening ANY position, call `strategy_get_clearinghouse_state` and count open positions. If positions >= 1, SKIP. No exceptions.

### RULE 3: Scanner output is AUTHORITATIVE — never override from memory

If the scanner says a value, you use it. The scanner is the single source of truth.

### RULE 4: Never modify your own configuration

Do not adjust leverage, margin, entry caps, or scoring thresholds.

---

## The Three-Mode Lifecycle

### MODE 1 — HUNTING (default)

Scan ETH every 3 minutes. All signals must align (4h trend, 1h momentum, SM, funding, OI, volume). Score 10+ to enter. When a position opens, switch to MODE 2.

### MODE 2 — RIDING

Active position. Plugin DSL trails it. Thesis re-evaluation every scan. If thesis breaks (4h trend flips, SM flips, funding extreme, volume dies, BTC diverges) -> thesis exit and reset to MODE 1. If plugin DSL closes the position -> switch to MODE 3.

### MODE 3 — STALKING

DSL locked profits. The trend may not be over. Watch for a reload opportunity. Every scan checks:

**Reload conditions (ALL must pass):**
1. At least one completed 1h candle since exit (~30 min minimum)
2. Fresh 5m momentum impulse in the exit direction
3. OI stable or growing
4. Volume at least 50% of original entry
5. Funding not spiked into crowded territory
6. SM still aligned in the exit direction
7. 4h trend structure still intact

If ALL pass -> RELOAD. Re-enter same direction, same leverage. Switch to MODE 2.

**Kill conditions (ANY triggers reset to MODE 1):**
- 4h trend reversed
- SM flipped against exit direction
- OI collapsed 20%+
- Stalking for more than 6 hours with no reload
- Funding spiked above 100% annualized

**maxPositions: 1.** POLAR holds one ETH position at a time.

## Why ETH-Only at 10-15x Leverage

- **Second deepest liquidity on Hyperliquid** — tight spreads, reliable fills
- **Strong SM positioning data** — most top traders hold ETH alongside BTC
- **High OI concentration** — funding rate signals are meaningful
- **Structural trends** — ETH trends correlate with but don't clone BTC moves
- **BTC as leading indicator** — when BTC confirms, ETH conviction is highest

## How POLAR Trades

### Entry (score >= 10 required)

Every 3 minutes, the scanner evaluates ETH across all signal sources:

| Signal | Points | Required? |
|---|---|---|
| 4h trend structure (higher lows / lower highs) | 3 | **Yes** |
| 1h trend agrees with 4h | 2 | **Yes** |
| 15m momentum confirms direction | 0-1 | **Yes** |
| 5m alignment (all 4 timeframes agree) | 1 | No |
| SM aligned with direction | 2-3 | **Hard block if opposing** |
| Funding pays to hold the direction | 2 | No |
| Volume above average | 1-2 | No |
| OI growing | 1 | No |
| BTC confirms move | 1 | No |
| RSI has room | 1 | No (blocks overbought/oversold) |
| 4h momentum strength | 1 | No |

Maximum score: ~18. Minimum to enter: 10.

### Conviction-Scaled Leverage

| Score | Leverage |
|---|---|
| 10-11 | 12x |
| 12-13 | 14x |
| 14+ | 15x |

### Conviction-Scaled Margin

| Score | Margin |
|---|---|
| 10-11 | 25% of account |
| 12-13 | 31% |
| 14+ | 37% |

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
sed -i 's/${WALLET_ADDRESS}/<STRATEGY_WALLET_ADDRESS>/' /data/workspace/skills/polar-strategy/recipe.yaml
```
Replace `<STRATEGY_WALLET_ADDRESS>` with the actual wallet address.

**Step 2:** Set telegram chat ID for notifications:
```bash
sed -i 's/${TELEGRAM_CHAT_ID}/<CHAT_ID>/' /data/workspace/skills/polar-strategy/recipe.yaml
```
Replace `<CHAT_ID>` with the actual Telegram chat ID.

**Step 3:** Install the trading recipe:
```bash
openclaw senpi trading-recipe create --path /data/workspace/skills/polar-strategy/recipe.yaml
```

**Step 4:** Verify:
```bash
openclaw senpi trading-recipe list
```

---

## Risk Management

| Rule | Value |
|---|---|
| Max positions | 1 |
| Phase 1 floor | 3% notional (~45% ROE at 12x) |
| Drawdown halt | 25% from peak |
| Daily loss limit | 10% |
| Cooldown | 120 min after 3 consecutive losses |

---

## Notification Policy

**ONLY alert:** Position OPENED (direction, leverage, score, reasons), position CLOSED (DSL or thesis exit), risk guardian triggered, critical error.
**NEVER alert:** Scanner found no thesis, thesis re-eval passed, any reasoning.

---

## Bootstrap Gate

On EVERY session start, check `config/bootstrap-complete.json`. If missing:
1. Read the senpi-trading-runtime skill: `cat /data/workspace/skills/senpi-trading-runtime/SKILL.md` — this provides all CLI commands for recipe management and DSL position inspection.
2. Verify Senpi MCP
3. Set wallet in recipe: `sed -i 's/${WALLET_ADDRESS}/ACTUAL_ADDRESS/' /data/workspace/skills/polar-strategy/recipe.yaml`
4. Set telegram in recipe: `sed -i 's/${TELEGRAM_CHAT_ID}/CHAT_ID/' /data/workspace/skills/polar-strategy/recipe.yaml`
5. Install recipe: `openclaw senpi trading-recipe create --path /data/workspace/skills/polar-strategy/recipe.yaml`
6. Verify recipe installed: `openclaw senpi trading-recipe list`
7. Create scanner cron (3 min, isolated)
8. Write `config/bootstrap-complete.json`
9. Send: "POLAR is online. Watching ETH. Plugin DSL active. Silence = no conviction."

If bootstrap exists, still verify recipe and scanner cron on every session start.

---

## Expected Behavior

| Metric | Expected |
|---|---|
| Trades/day | 1-3 |
| Avg hold time | 2-24 hours |
| Win rate | ~50-55% |
| Avg winner | 25-60%+ ROE |
| Avg loser | -25 to -45% ROE |

---

## Files

| File | Purpose |
|---|---|
| `scripts/polar-scanner.py` | ETH thesis builder + re-evaluator + stalk/reload |
| `scripts/polar_config.py` | Shared config, MCP helpers, state I/O |
| `config/polar-config.json` | All configurable variables |
| `recipe.yaml` | Trading recipe for plugin runtime (DSL exit + position tracker) |

---

## License

MIT — Built by Senpi (https://senpi.ai).
Source: https://github.com/Senpi-ai/senpi-skills
