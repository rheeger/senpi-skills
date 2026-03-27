---
name: condor-strategy
description: >-
  CONDOR v1.0.1 — Multi-asset alpha hunter. Grizzly's three-mode lifecycle
  (HUNTING → RIDING → STALKING → RELOAD) across BTC, ETH, SOL, and HYPE.
  Evaluates all four every scan, commits to the single strongest thesis.
  One position at a time. Maximum conviction. Always in the best trade.
  DSL exit managed by plugin runtime via recipe.yaml.
license: MIT
metadata:
  author: jason-goldberg
  version: "2.0"
  platform: senpi
  exchange: hyperliquid
  based_on: grizzly-v2.1
  requires:
    - senpi-trading-runtime
---

# CONDOR v1.0.1 — Multi-Asset Alpha Hunter

Four assets. One position. Always the strongest thesis.

## Why CONDOR Exists

Polar (+28%, ETH only), Wolverine (+0%, HYPE only), and Grizzly (BTC only) each proved that the three-mode lifecycle works on single assets. But they sit idle when their asset isn't moving. Polar waited through thousands of scans while HYPE ran 40%.

Condor watches BTC, ETH, SOL, and HYPE simultaneously. Every 3 minutes, it scores all four and commits to the single highest-conviction thesis. When that thesis dies, it evaluates all four again. Always in the best trade available.

## CRITICAL AGENT RULES — READ BEFORE ANYTHING ELSE

### RULE 1: MAX 1 POSITION — check before EVERY entry

Before opening ANY position, call `strategy_get_clearinghouse_state` and count open positions. If positions >= 1, SKIP. No exceptions.

### RULE 2: Scanner output is AUTHORITATIVE — never override from memory

If the scanner says a value, you use it. The scanner is the single source of truth.

### RULE 3: Verify recipe is installed on every session start

Run `openclaw senpi trading-recipe list`. Recipe must be listed. The position tracker and DSL exit are handled by the plugin runtime.

### RULE 4: Never retry timed-out position creation

If `create_position` times out, check clearinghouse state. If position exists, the position tracker will pick it up automatically. If not, wait for next scan.

### RULE 5: Never modify your own configuration

Do not adjust leverage, margin, entry caps, or scoring thresholds.

---

## Three-Mode Lifecycle (Same as Grizzly)

**MODE 1 — HUNTING:** Score all 4 assets across 4 timeframes, SM positioning, funding, volume, OI, and correlation. Enter the highest score (10+ required). If none qualify, wait.

**MODE 2 — RIDING:** Monitor the active position's thesis every scan. If SM flips, 4H trend breaks, funding goes extreme, or volume dies — thesis exit immediately. If DSL closes the position — transition to MODE 3.

**MODE 3 — STALKING:** Watch the SAME asset for reload conditions (fresh impulse, volume alive, SM aligned, 4H intact). If reload passes, re-enter. If thesis dies during stalk, reset to MODE 1 and evaluate all 4 assets fresh.

## Correlation Map

| Asset | Correlation Asset | Relationship |
|---|---|---|
| BTC | ETH | Must confirm |
| ETH | BTC | Must confirm |
| SOL | BTC | Must confirm |
| HYPE | BTC | **Bonus only** — HYPE moves independently |

HYPE's BTC correlation is never a block or thesis exit signal. When BTC confirms HYPE, it's a +2 score bonus. When BTC diverges, it's ignored. The other three assets require correlation confirmation.

## Exit Management

DSL exit is handled by the plugin runtime via `recipe.yaml`. The `position_tracker` scanner auto-detects position opens/closes on-chain. See `recipe.yaml` for configuration details.

**Monitor positions:**
- `openclaw senpi dsl positions` — list all DSL-tracked positions
- `openclaw senpi dsl inspect <ASSET>` — full position details

## Conviction-Scaled Margin

Condor evaluates all 4 assets and picks the single best. When it enters, this is the highest-conviction trade available across the entire market. Margin scales accordingly:

| Score | Margin | Rationale |
|---|---|---|
| 10-11 | 25% | Base conviction |
| 12-13 | 35% | Strong thesis — best of 4 assets |
| 14+ | 45% | Extreme conviction — rare, maximum deployment |
| RELOAD | 35% | Thesis confirmed by parent trade |

At 10x leverage and 45% margin on a $1,000 account, that's $4,500 notional. On an 85% ROE trade (like Polar's ETH long), that's +$382. On a -30% absolute floor exit, that's -$135. The risk:reward is appropriate for a score-14 thesis that beat three other assets.

## Notification Policy

**ONLY alert:** Position OPENED (asset, direction, score, all 4 asset scores), position CLOSED, thesis exit, risk guardian. **NEVER:** Scanner found nothing, STALKING status, HUNTING status.

## Recipe Setup

**Step 1:** Set your strategy wallet address in the recipe:
```bash
sed -i 's/${WALLET_ADDRESS}/<STRATEGY_WALLET_ADDRESS>/' /data/workspace/skills/condor-strategy/recipe.yaml
```
Replace `<STRATEGY_WALLET_ADDRESS>` with the actual wallet address.

**Step 2:** Set telegram chat ID for notifications:
```bash
sed -i 's/${TELEGRAM_CHAT_ID}/<CHAT_ID>/' /data/workspace/skills/condor-strategy/recipe.yaml
```
Replace `<CHAT_ID>` with the actual Telegram chat ID.

**Step 3:** Install the trading recipe:
```bash
openclaw senpi trading-recipe create --path /data/workspace/skills/condor-strategy/recipe.yaml
```

**Step 4:** Verify:
```bash
openclaw senpi trading-recipe list
```

## Crons

| Cron | Interval | Session |
|---|---|---|
| Scanner | 3 min | main |

## Bootstrap Gate

On EVERY session start, check `config/bootstrap-complete.json`. If missing:
1. Read the senpi-trading-runtime skill: `cat /data/workspace/skills/senpi-trading-runtime/SKILL.md`
2. Verify Senpi MCP
3. Set wallet in recipe: `sed -i 's/${WALLET_ADDRESS}/ACTUAL_ADDRESS/' /data/workspace/skills/condor-strategy/recipe.yaml`
4. Set telegram in recipe: `sed -i 's/${TELEGRAM_CHAT_ID}/CHAT_ID/' /data/workspace/skills/condor-strategy/recipe.yaml`
5. Install recipe: `openclaw senpi trading-recipe create --path /data/workspace/skills/condor-strategy/recipe.yaml`
6. Verify recipe installed: `openclaw senpi trading-recipe list`
7. Create scanner cron (3 min, main)
8. Write `config/bootstrap-complete.json`
9. Send: "CONDOR v1.0.1 online. Watching BTC, ETH, SOL, HYPE. Silence = no conviction."

If bootstrap exists, still verify recipe and scanner cron on every session start.

## Files

| File | Purpose |
|---|---|
| `scripts/condor-scanner.py` | Multi-asset lifecycle scanner |
| `scripts/condor_config.py` | Self-contained config helper |
| `config/condor-config.json` | All parameters |
| `recipe.yaml` | Trading recipe for plugin runtime (DSL exit + position tracker) |

## License

MIT — Built by Senpi (https://senpi.ai).
