---
name: hydra
description: >-
  HYDRA v2.0 — Multi-source squeeze scanner. Detects crowded positions across
  200+ crypto assets using 6 independent signal sources (FDD, LCD, OIS, MED, EM,
  OPP), scores candidates on a 0-110 scale, enters with conviction-based sizing,
  and manages positions with trailing stops. Includes independent
  monitor watchdog (3rd cron) for account health, signal reversal detection,
  and force-close capabilities. XYZ banned. Leverage capped at 10x.
  DSL exit managed by plugin runtime via recipe.yaml.
license: MIT
metadata:
  author: jason-goldberg
  version: "2.0"
  platform: senpi
  exchange: hyperliquid
  config_source: liquidity-hunter-v3-refactored
  requires:
    - senpi-trading-runtime
---

# 🐉 HYDRA v2.0 — Multi-Source Squeeze Scanner

Six signal sources. One conviction score. Cut losers fast, let winners run to Tier 4.

---

## ⛔ CRITICAL AGENT RULES — READ BEFORE ANYTHING ELSE

### RULE 1: Install path is `/data/workspace/skills/hydra/`

The skill MUST be installed to exactly this path.

### RULE 2: MAX 3 POSITIONS — check before EVERY entry

Before opening ANY position, call `strategy_get_clearinghouse_state` and count open positions. If positions >= 3, SKIP. The scanner also checks this, but you MUST verify independently.

### RULE 3: Scanner output is AUTHORITATIVE — never override from memory

If the scanner says leverage 5x, you use 5x. Not 10x from memory. Not 50x from "what worked before." The scanner calculates leverage dynamically based on conviction tier and asset max leverage, capped at 10x. The scanner is the single source of truth.

### RULE 4: Verify recipe is installed on every session start

Run `openclaw senpi trading-recipe list`. Recipe must be listed. The position tracker and DSL exit are handled by the plugin runtime.

### RULE 5: Never retry timed-out position creation

If `create_position` times out, check clearinghouse state. If position exists, the position tracker will pick it up automatically. If not, wait for next scan.

### RULE 6: Never modify your own configuration

Do not adjust leverage, margin, scoring weights, tier thresholds, or any other parameter. Every agent that self-modified made things worse.

### RULE 7: Respect the monitor's force-close actions

If the monitor outputs a `FORCE_CLOSE` or `FORCE_CLOSE_ALL` action, execute it immediately. Do not second-guess, delay, or override the monitor. It runs independently for a reason.

---

## Core Thesis

When too many traders pile into one side (usually shorts), they become vulnerable to a liquidation squeeze. HYDRA detects this crowding across 6 independent signals, waits for sufficient confluence, and enters the counter-trade. The edge is cutting losers fast and letting winners run to upper trailing tiers — a "Tier 4 hunter."

---

## Signal Sources (6)

### Source 1: FDD — Funding Divergence Detector (0-30 pts, PRIMARY GATE)

No trade is considered without an FDD signal. Analyzes funding rate to detect SHORT_CROWDING (deeply negative → go long) or LONG_CROWDING (deeply positive → go short). Confidence from percentile extremity + persistence (consecutive hours crowded).

### Source 2: LCD — Liquidation Cascade Detector (0-25 pts)

Estimates liquidation cluster proximity from OI, funding, and price action. Detects SHORT_LIQUIDATION_RISK / LONG_LIQUIDATION_RISK. +10 cascade bonus if price is already moving through the cluster.

### Source 3: OIS — Open Interest Surge Detector (0-20 pts)

Tracks OI changes via local snapshots (state/oi-history/). Detects OI_SURGE (new leverage piling in) and OI_UNWIND. Requires history accumulation — first few scans will have insufficient data.

### Source 4: MED — Momentum Exhaustion Detector (-10 to +5 pts)

Dual role: +5 if momentum intact (CLEAR), -5 if fading (FADE), -10 if exhausted (EXHAUSTED). Also drives market regime detection (TRENDING/MIXED/RANGE).

### Source 5: EM — Emerging Movers (-8 to +15 pts)

SM consensus from leaderboard_get_markets + leaderboard_get_top. +15 for strong same-direction confirmation (conviction 3+, 50+ traders). -8 for strong opposing SM.

### Source 6: OPP — Opportunity Scanner (-999 to +10 pts)

Final gate: hourly trend alignment. Counter-trend = hard skip (-999). Multi-pillar scoring: price alignment, volume, spread quality.

---

## Conviction Tiers & Sizing

```
Score = FDD(0-30) + LCD(0-25) + OIS(0-20) + MED(-10 to +5) + EM(-8 to +15) + OPP(-999 to +10)
Maximum possible: 110
```

| Tier | Score | Status | Margin | Leverage |
|---|---|---|---|---|
| NO_TRADE | < 55 | Blocked | — | — |
| LOW | 40-54 | PERMANENTLY DISABLED | — | — |
| MEDIUM | 55-74 | Active | base × 60% | 50-65% of asset max, cap 10x |
| HIGH | 75-110 | Active | base × 100% | 70-85% of asset max, cap 10x |

Base margin = wallet × 15%. Per-asset cap 25%. Total deployed cap 55%.

---

## Exit Management

DSL exit is handled by the plugin runtime via `recipe.yaml`. The `position_tracker` scanner auto-detects position opens/closes on-chain. See `recipe.yaml` for configuration details.

**Monitor positions:**
- `openclaw senpi dsl positions` — list all DSL-tracked positions
- `openclaw senpi dsl inspect <ASSET>` — full position details

---

## Monitor Watchdog

Runs independently. Checks:
1. **Account health** — drawdown cap 25%
2. **Capital exposure** — deployed margin vs 60% threshold
3. **Signal reversal** — re-runs FDD: if original thesis flipped, force-close
4. **Daily loss limit** — 10% cumulative
5. **Consecutive losses** — 3 → cooldown gate

Can output: FORCE_CLOSE (single position), FORCE_CLOSE_ALL (account health), GATE_CLOSE/GATE_COOLDOWN.

---

## Self-Learning

Per-tier win/loss stats tracked in runtime.json. If a tier's win rate drops below 15% over 8+ trades, that tier is auto-disabled. LOW tier is permanently disabled (0% WR proven in production).

---

## Recipe Setup

**Step 1:** Set your strategy wallet address in the recipe:
```bash
sed -i 's/${WALLET_ADDRESS}/<STRATEGY_WALLET_ADDRESS>/' /data/workspace/skills/hydra/recipe.yaml
```
Replace `<STRATEGY_WALLET_ADDRESS>` with the actual wallet address.

**Step 2:** Set telegram chat ID for notifications:
```bash
sed -i 's/${TELEGRAM_CHAT_ID}/<CHAT_ID>/' /data/workspace/skills/hydra/recipe.yaml
```
Replace `<CHAT_ID>` with the actual Telegram chat ID.

**Step 3:** Install the trading recipe:
```bash
openclaw senpi trading-recipe create --path /data/workspace/skills/hydra/recipe.yaml
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
3. Set wallet in recipe: `sed -i 's/${WALLET_ADDRESS}/ACTUAL_ADDRESS/' /data/workspace/skills/hydra/recipe.yaml`
4. Set telegram in recipe: `sed -i 's/${TELEGRAM_CHAT_ID}/CHAT_ID/' /data/workspace/skills/hydra/recipe.yaml`
5. Install recipe: `openclaw senpi trading-recipe create --path /data/workspace/skills/hydra/recipe.yaml`
6. Verify recipe installed: `openclaw senpi trading-recipe list`
7. Remove old DSL cron (if upgrading): run `openclaw crons list`, delete any cron containing `dsl-v5.py` via `openclaw crons delete <id>`
8. Create scanner cron (5 min, main)
8. Create monitor cron (5 min, isolated)
9. Write `config/bootstrap-complete.json`
10. Send: "🐉 HYDRA v2.0 online. 6-source squeeze scanner + monitor watchdog. FDD primary gate. DSL managed by plugin runtime. Silence = no squeeze."

If bootstrap exists, still verify recipe and scanner cron on every session start.

---

## Risk Management

| Rule | Value |
|---|---|
| Max positions | 3 |
| Max entries/day | 6 |
| Leverage cap | 10x |
| Total deployed cap | 55% of wallet |
| Per-asset cap | 25% of wallet |
| Daily loss limit | 10% |
| Drawdown cap | 25% |
| Per-asset cooldown | 120 min |
| Consecutive losses | 3 → 30 min cooldown |
| XYZ equities | Banned |
| LOW tier | Permanently disabled |

---

## Notification Policy

**ONLY alert:** Position OPENED (asset, direction, score, tier, FDD signal), position CLOSED (P&L, reason), monitor force-close (asset, reason), risk guardian triggered, critical error.

**NEVER alert:** Scanner found no squeeze signals, signals filtered, monitor all-clear, any reasoning.

---

## Expected Behavior

| Metric | Expected |
|---|---|
| Trades/day | 2-5 (some zero-trade days in RANGE regime) |
| Win rate | ~40% |
| Avg winner | 3-5x larger than avg loser (Tier 4 hunter) |
| Max concurrent | 3 positions |
| Scan cycle | 5 min scanner, 5 min monitor |

---

## Files

| File | Purpose |
|---|---|
| `scripts/hydra-scanner.py` | 6-source scoring + signal output |
| `scripts/hydra-monitor.py` | Independent watchdog (account health, reversal, loss limits) |
| `scripts/hydra_config.py` | Config helper (mcporter CLI, clearinghouse parsing, cooldowns, OI history) |
| `config/hydra-config.json` | All configurable parameters |
| `recipe.yaml` | Trading recipe for plugin runtime (DSL exit + position tracker) |

---

## License

MIT — Built by Senpi (https://senpi.ai).
Source: https://github.com/Senpi-ai/senpi-skills
