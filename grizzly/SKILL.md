---
name: grizzly-strategy
description: >-
  GRIZZLY v2.0 — BTC alpha hunter with position lifecycle. Single asset, every signal
  (SM, funding, OI, 4TF trend, volume, ETH correlation). Three-mode lifecycle:
  HUNTING (scan for entry) → RIDING (DSL trails) → STALKING (watch for reload on dip).
  After DSL takes profit, watches for fresh momentum impulse while confirming macro thesis
  is intact. If thesis dies, resets. If dip reloads, re-enters.
  DSL exit managed by plugin runtime via recipe.yaml.
license: MIT
metadata:
  author: jason-goldberg
  version: "2.1.1"
  platform: senpi
  exchange: hyperliquid
  requires:
    - senpi-trading-runtime
---

# GRIZZLY v2.0 — BTC Alpha Hunter with Position Lifecycle

One asset. Every signal. Maximum conviction. Now with reload-on-dip.

GRIZZLY stares at BTC and nothing else. Every signal source available — smart money positioning, funding rate, open interest, 4-timeframe trend structure, volume, ETH correlation — feeds into a single thesis: is there a high-conviction BTC trade right now?

## CRITICAL AGENT RULES — READ BEFORE ANYTHING ELSE

### RULE 1: Verify recipe is installed on every session start

Run `openclaw senpi trading-recipe list`. Recipe must be listed. The position tracker and DSL exit are handled by the plugin runtime.

### RULE 2: Never retry timed-out position creation

If `create_position` times out, check clearinghouse state. If position exists, the position tracker will pick it up automatically. If not, wait for next scan.

### RULE 3: Never modify your own configuration

Do not adjust leverage, margin, entry caps, or scoring thresholds.

---

## What's New in v2.0: The Three-Mode Lifecycle

v1.0 treated every entry as independent. After DSL closed a winning trade, GRIZZLY immediately scanned for a new entry — often re-entering on a minor dip that was just the aftershock of the move it just profited from.

v2.0 adds a STALKING mode between exits and new entries. After DSL takes profit, GRIZZLY watches the asset for a genuine reload opportunity while confirming the macro thesis is still alive.

### MODE 1 — HUNTING (default)

Normal behavior. Scan BTC every 3 minutes. All signals must align (4h trend, 1h momentum, SM, funding, OI, volume). Score 10+ to enter. When a position opens, switch to MODE 2.

### MODE 2 — RIDING

Active position. DSL trails it. Thesis re-evaluation every scan. If thesis breaks (4h trend flips, SM flips, funding extreme, volume dies, ETH diverges) — thesis exit and reset to MODE 1 (thesis is dead, don't stalk). If DSL closes the position — switch to MODE 3.

### MODE 3 — STALKING

DSL locked profits. The trend may not be over. Watch for a reload opportunity. Every scan checks:

**Reload conditions (ALL must pass):**
1. At least one completed 1h candle since exit (minimum ~30 min)
2. Fresh 5m momentum impulse in the exit direction (new acceleration, not dead cat bounce)
3. OI stable or growing (not collapsing from profit-taking)
4. Volume at least 50% of what powered the original entry
5. Funding not spiked into crowded territory (< 50% annualized)
6. SM still aligned in the exit direction
7. 4h trend structure still intact

If ALL pass — RELOAD. Re-enter same direction, same leverage. Switch to MODE 2.

**Kill conditions (ANY triggers reset to MODE 1):**
- 4h trend reversed
- SM flipped against exit direction
- OI collapsed 20%+
- Stalking for more than 6 hours with no reload
- Funding spiked above 100% annualized

The loop: HUNTING — RIDING — STALKING — RELOAD — RIDING — STALKING — ... until a kill condition fires — HUNTING.

**maxPositions: 1.** GRIZZLY holds one BTC position at a time. All capital, all attention, one trade.

## Why BTC-Only at High Leverage

Every other skill scans 10-230 assets. GRIZZLY scans one. The tradeoff: fewer trades, but every signal source is concentrated on the asset with the most data.

- **Deepest liquidity on Hyperliquid** — no slippage even at 20x
- **Most SM data** — every whale trades BTC, leaderboard positioning is most meaningful
- **Highest OI concentration** — funding rate signals are strongest
- **Tightest spreads** — maker orders fill reliably
- **Structural moves** — BTC trends last hours to days, not minutes

High leverage amplifies the edge. At 15x, a 2% BTC move = 30% ROE. At 20x, it's 40% ROE. BTC's structural, sustained trends are the ideal setup for leveraged conviction trades with wide trailing stops.

## How GRIZZLY Trades

### Entry (score >= 10 required)

Every 3 minutes, the scanner evaluates BTC across all signal sources:

| Signal | Points | Required? |
|---|---|---|
| 4h trend structure (higher lows / lower highs) | 3 | **Yes** — no entry without macro structure |
| 1h trend agrees with 4h | 2 | **Yes** |
| 15m momentum confirms direction | 0-1 | **Yes** (min 0.1%) |
| 5m alignment (all 4 timeframes agree) | 1 | No |
| SM aligned with direction | 2-3 | **Hard block if opposing** |
| Funding pays to hold the direction | 2 | No |
| Volume above average | 1-2 | No |
| OI growing (new money entering) | 1 | No |
| ETH confirms BTC's move | 1 | No |
| RSI has room | 1 | No (but blocks overbought/oversold) |
| 4h momentum strength | 1 | No |

Maximum score: ~18. Minimum to enter: 10. This means at least 4h structure + 1h agreement + SM aligned + one more booster.

### Conviction-Scaled Leverage

| Score | Leverage |
|---|---|
| 10-11 | 15x |
| 12-13 | 18x |
| 14+ | 20x |

### Conviction-Scaled Margin

| Score | Margin |
|---|---|
| 10-11 | 30% of account |
| 12-13 | 37% |
| 14+ | 45% |

### Hold (thesis re-evaluation every 3 min)

GRIZZLY re-evaluates the thesis every scan. The position holds as long as:
- 4h trend structure hasn't flipped
- SM hasn't flipped against the position
- Funding hasn't gone extreme against the position
- Volume hasn't dried up for 3+ hours
- ETH isn't strongly diverging from BTC

If ANY of these break — thesis exit. The agent closes because the reason it entered is dead.

## Exit Management

DSL exit is handled by the plugin runtime via `recipe.yaml`. The `position_tracker` scanner auto-detects position opens/closes on-chain. See `recipe.yaml` for configuration details.

**Monitor positions:**
- `openclaw senpi dsl positions` — list all DSL-tracked positions
- `openclaw senpi dsl inspect <ASSET>` — full position details

## Risk Management

| Rule | Value | Notes |
|---|---|---|
| Max positions | 1 | One BTC trade at a time |
| Phase 1 floor | 3.5% notional | ~52% ROE at 15x, ~70% at 20x |
| G5 per-position cap | 10% of account | Wider than other skills — BTC conviction |
| G2 drawdown halt | 25% from peak | Halt all trading |
| Daily loss limit | 10% | |
| Cooldown | 120 min after 3 consecutive losses | Long — BTC conviction trades shouldn't chain-fail |

## Recipe Setup

**Step 1:** Set your strategy wallet address in the recipe:
```bash
sed -i 's/${WALLET_ADDRESS}/<STRATEGY_WALLET_ADDRESS>/' /data/workspace/skills/grizzly-strategy/recipe.yaml
```
Replace `<STRATEGY_WALLET_ADDRESS>` with the actual wallet address.

**Step 2:** Set telegram chat ID for notifications:
```bash
sed -i 's/${TELEGRAM_CHAT_ID}/<CHAT_ID>/' /data/workspace/skills/grizzly-strategy/recipe.yaml
```
Replace `<CHAT_ID>` with the actual Telegram chat ID.

**Step 3:** Install the trading recipe:
```bash
openclaw senpi trading-recipe create --path /data/workspace/skills/grizzly-strategy/recipe.yaml
```

**Step 4:** Verify:
```bash
openclaw senpi trading-recipe list
```

## Crons

| Cron | Interval | Session | Purpose |
|---|---|---|---|
| Scanner | 3 min | isolated | Thesis builder (if flat) + thesis re-evaluator (if holding) |

## Bootstrap Gate

On EVERY session, check `config/bootstrap-complete.json`. If missing:
1. Read the senpi-trading-runtime skill: `cat /data/workspace/skills/senpi-trading-runtime/SKILL.md`
2. Verify Senpi MCP
3. Set wallet in recipe: `sed -i 's/${WALLET_ADDRESS}/ACTUAL_ADDRESS/' /data/workspace/skills/grizzly-strategy/recipe.yaml`
4. Set telegram in recipe: `sed -i 's/${TELEGRAM_CHAT_ID}/CHAT_ID/' /data/workspace/skills/grizzly-strategy/recipe.yaml`
5. Install recipe: `openclaw senpi trading-recipe create --path /data/workspace/skills/grizzly-strategy/recipe.yaml`
6. Verify recipe installed: `openclaw senpi trading-recipe list`
7. Create scanner cron (3 min, isolated)
8. Write `config/bootstrap-complete.json`
9. Send: "GRIZZLY is online. Watching BTC. Silence = no conviction."

If bootstrap exists, still verify recipe and scanner cron on every session start.

## Notification Policy

**ONLY alert:** BTC position OPENED (direction, leverage, score, thesis reasons), position CLOSED (DSL or thesis exit with reason), risk guardian triggered, critical error.
**NEVER alert:** Scanner found no thesis, thesis re-evaluation passed, any reasoning.
All crons isolated. `NO_REPLY` for idle cycles. No rogue processes.

## Expected Behavior

| Metric | Expected |
|---|---|
| Trades/day | 1-3 (BTC conviction trades are rare) |
| Avg hold time | 2-24 hours |
| Win rate | ~50-55% |
| Avg winner | 30-80%+ ROE (high leverage + infinite trailing) |
| Avg loser | -30 to -50% ROE (wide floors for BTC) |
| Fee drag/day | $3-10 (1-3 maker entries) |
| Profit factor | Target 1.5-2.5 (big winners, managed losers) |

## Files

| File | Purpose |
|---|---|
| `scripts/grizzly-scanner.py` | BTC thesis builder + re-evaluator |
| `scripts/grizzly_config.py` | Shared config, MCP helpers, state I/O |
| `config/grizzly-config.json` | All configurable variables |
| `recipe.yaml` | Trading recipe for plugin runtime (DSL exit + position tracker) |

## License

MIT — Built by Senpi (https://senpi.ai).
Source: https://github.com/Senpi-ai/senpi-skills

## Changelog

### v2.1.1
- DSL exit migrated to plugin runtime via recipe.yaml
- Scanner DSL code removed (position_tracker handles position detection)
- Leverage capped at 10x (was 15-20x)
