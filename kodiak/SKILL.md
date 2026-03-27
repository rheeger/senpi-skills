---
name: kodiak-strategy
description: >-
  KODIAK v1.0 — SOL alpha hunter with position lifecycle. Single asset, every signal
  (SM, funding, OI, 4TF trend, volume, BTC correlation). Three-mode lifecycle:
  HUNTING (scan for entry) / RIDING (DSL trails) / STALKING (watch for reload on dip).
  After DSL takes profit, watches for fresh momentum impulse while confirming macro thesis
  is intact. If thesis dies, resets. If dip reloads, re-enters.
  DSL exit managed by plugin runtime via recipe.yaml.
license: MIT
metadata:
  author: jason-goldberg
  version: "2.0"
  platform: senpi
  exchange: hyperliquid
  base_skill: grizzly-v2.0
  requires:
    - senpi-trading-runtime
---

# KODIAK v1.0 — SOL Alpha Hunter with Position Lifecycle

One asset. Every signal. Maximum conviction. Reload-on-dip.

KODIAK stares at SOL and nothing else. Every signal source available — smart money positioning, funding rate, open interest, 4-timeframe trend structure, volume, BTC correlation — feeds into a single thesis: is there a high-conviction SOL trade right now?

Based on GRIZZLY v2.0's three-mode lifecycle, adapted for SOL's volatility profile.

## The Three-Mode Lifecycle

### MODE 1 — HUNTING (default)

Scan SOL every 3 minutes. All signals must align (4h trend, 1h momentum, SM, funding, OI, volume). Score 10+ to enter. When a position opens, switch to MODE 2.

### MODE 2 — RIDING

Active position. DSL trails it via the plugin runtime. Thesis re-evaluation every scan. If thesis breaks (4h trend flips, SM flips, funding extreme, volume dies, BTC diverges) -> thesis exit and reset to MODE 1. If DSL closes the position -> switch to MODE 3.

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

**maxPositions: 1.** KODIAK holds one SOL position at a time.

## Why SOL-Only at 7-12x Leverage

- **High volatility** — SOL moves 5-10% in hours, amplifying conviction trades
- **Growing liquidity on Hyperliquid** — increasingly tradeable at size
- **Ecosystem momentum** — SOL trends driven by DeFi/NFT/memecoin cycles
- **BTC as regime filter** — SOL trends rarely sustain against a BTC reversal
- **Lower leverage compensates for volatility** — 10x on SOL ≈ 15x on BTC in terms of realized move

## How KODIAK Trades

### Entry (score >= 10 required)

Every 3 minutes, the scanner evaluates SOL across all signal sources:

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
| 10-11 | 10x |
| 12-13 | 11x |
| 14+ | 12x |

### Conviction-Scaled Margin

| Score | Margin |
|---|---|
| 10-11 | 20% of account |
| 12-13 | 25% |
| 14+ | 30% |

## Exit Management

DSL exit is handled by the plugin runtime via `recipe.yaml`. The `position_tracker` scanner auto-detects position opens/closes on-chain. See `recipe.yaml` for configuration details.

**Monitor positions:**
- `openclaw senpi dsl positions` — list all DSL-tracked positions
- `openclaw senpi dsl inspect <ASSET>` — full position details

## Risk Management

| Rule | Value |
|---|---|
| Max positions | 1 |
| Phase 1 floor | 2.5% notional (~25% ROE at 10x) |
| Drawdown halt | 25% from peak |
| Daily loss limit | 10% |
| Cooldown | 120 min after 3 consecutive losses |

## Recipe Setup

**Step 1:** Set your strategy wallet address in the recipe:
```bash
sed -i 's/${WALLET_ADDRESS}/<STRATEGY_WALLET_ADDRESS>/' /data/workspace/skills/kodiak-strategy/recipe.yaml
```
Replace `<STRATEGY_WALLET_ADDRESS>` with the actual wallet address.

**Step 2:** Set telegram chat ID for notifications:
```bash
sed -i 's/${TELEGRAM_CHAT_ID}/<CHAT_ID>/' /data/workspace/skills/kodiak-strategy/recipe.yaml
```
Replace `<CHAT_ID>` with the actual Telegram chat ID.

**Step 3:** Install the trading recipe:
```bash
openclaw senpi trading-recipe create --path /data/workspace/skills/kodiak-strategy/recipe.yaml
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
3. Set wallet in recipe: `sed -i 's/${WALLET_ADDRESS}/ACTUAL_ADDRESS/' /data/workspace/skills/kodiak-strategy/recipe.yaml`
4. Set telegram in recipe: `sed -i 's/${TELEGRAM_CHAT_ID}/CHAT_ID/' /data/workspace/skills/kodiak-strategy/recipe.yaml`
5. Install recipe: `openclaw senpi trading-recipe create --path /data/workspace/skills/kodiak-strategy/recipe.yaml`
6. Verify recipe installed: `openclaw senpi trading-recipe list`
7. Create scanner cron (3 min, isolated)
8. Write `config/bootstrap-complete.json`
9. Send: "KODIAK is online. Watching SOL. DSL managed by plugin runtime. Silence = no conviction."

If bootstrap exists, still verify recipe and scanner cron on every session start.

---

## Notification Policy

**ONLY alert:** Position OPENED (direction, leverage, score, reasons), position CLOSED (DSL or thesis exit), risk guardian triggered, critical error.
**NEVER alert:** Scanner found no thesis, thesis re-eval passed, any reasoning.

---

## Expected Behavior

| Metric | Expected |
|---|---|
| Trades/day | 1-3 |
| Avg hold time | 1-12 hours |
| Win rate | ~45-55% |
| Avg winner | 20-50%+ ROE |
| Avg loser | -20 to -40% ROE |

---

## Files

| File | Purpose |
|---|---|
| `scripts/kodiak-scanner.py` | SOL thesis builder + re-evaluator + stalk/reload |
| `scripts/kodiak_config.py` | Shared config, MCP helpers, state I/O |
| `config/kodiak-config.json` | All configurable variables |
| `recipe.yaml` | Trading recipe for plugin runtime (DSL exit + position tracker) |

---

## License

MIT — Built by Senpi (https://senpi.ai).
Source: https://github.com/Senpi-ai/senpi-skills
