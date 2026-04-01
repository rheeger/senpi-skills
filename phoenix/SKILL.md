---
name: phoenix-strategy
description: >-
  PHOENIX v1.0.1 — Contribution velocity scanner. Finds assets where SM profit
  contribution is accelerating but price hasn't moved yet. This divergence is
  the pre-move signal. One API call, zero state files, minimal complexity.
  DSL exit managed by plugin runtime via runtime.yaml.
license: MIT
metadata:
  author: jason-goldberg
  version: "1.0.1"
  platform: senpi
  exchange: hyperliquid
  requires:
    - senpi-trading-runtime
---

# 🔥 PHOENIX v1.0.1 — Contribution Velocity Scanner

SM knows something the market doesn't. Find the divergence. Enter before the move.

---

## ⛔ CRITICAL AGENT RULES — READ BEFORE ANYTHING ELSE

### RULE 1: Install path is `/data/workspace/skills/phoenix-strategy/`

The skill MUST be installed to exactly this path.

### RULE 2: MAX 3 POSITIONS — check before EVERY entry

Before opening ANY position, call `strategy_get_clearinghouse_state` and count open positions. If positions >= 3, SKIP.

### RULE 3: THE SCANNER DOES NOT EXIT POSITIONS

When the scanner sees active positions, it outputs NO_REPLY. DSL is the ONLY exit mechanism, managed by the plugin runtime. The scanner does NOT re-evaluate thesis.

### RULE 4: Verify runtime is installed on every session start

Run `openclaw senpi runtime list`. Runtime must be listed. The position tracker and DSL exit are handled by the plugin runtime.

### RULE 5: Never retry timed-out position creation

If `create_position` times out, check clearinghouse state first.

### RULE 6: Never modify your own configuration

No adjustments to leverage, margin, scoring, or any parameter.

### RULE 7: MAX 6 ENTRIES PER DAY — non-negotiable

---

## The Phoenix Signal

Phoenix finds one specific pattern: **contribution velocity divergence**.

When SM is rapidly accumulating in a direction (measured by `contribution_pct_change_4h`) but the price hasn't moved yet, smart money knows something the market doesn't. Phoenix enters before the crowd catches on.

**Best trade:** HYPE SHORT — 54x divergence ratio, score 9. SM flooded into shorts while price was flat. Position held 2.6 days, peaked at +50.8% ROE, realized +$101.

**One API call.** `leaderboard_get_markets` provides contribution change, price change, SM concentration, and trader count. No scan history needed. No state files. The divergence is computed fresh every scan.

---

## Exit Management

DSL exit is handled by the plugin runtime via `runtime.yaml`. The `position_tracker` scanner auto-detects position opens/closes onchain. See `runtime.yaml` for configuration details.

**Entry flow:**
1. Scanner outputs signal
2. Verify positions < 2
3. Call `create_position`
4. Send ONE notification: position opened
5. `position_tracker` detects the new position automatically
6. Plugin DSL monitor applies trailing stop-loss protection

**Monitor positions:**
- `openclaw senpi dsl positions` — list all DSL-tracked positions
- `openclaw senpi dsl inspect <ASSET>` — full position details

---

## Runtime Setup

**Step 1:** Set your strategy wallet address in the recipe:
```bash
sed -i 's/${WALLET_ADDRESS}/<STRATEGY_WALLET_ADDRESS>/' /data/workspace/skills/phoenix-strategy/runtime.yaml
```
Replace `<STRATEGY_WALLET_ADDRESS>` with the actual wallet address.

**Step 2:** Set telegram chat ID for notifications:
```bash
sed -i 's/${TELEGRAM_CHAT_ID}/<CHAT_ID>/' /data/workspace/skills/phoenix-strategy/runtime.yaml
```
Replace `<CHAT_ID>` with the actual Telegram chat ID.

**Step 3:** Install the runtime:
```bash
openclaw senpi runtime create --path /data/workspace/skills/phoenix-strategy/runtime.yaml
```

**Step 4:** Verify:
```bash
openclaw senpi runtime list
```

---

## Bootstrap Gate

On EVERY session start, check `config/bootstrap-complete.json`. If missing:
1. Read the senpi-trading-runtime skill: `cat /data/workspace/skills/senpi-trading-runtime/SKILL.md`
2. Verify Senpi MCP
3. Set wallet in runtime: `sed -i 's/${WALLET_ADDRESS}/ACTUAL_ADDRESS/' /data/workspace/skills/phoenix-strategy/runtime.yaml`
4. Set telegram in runtime: `sed -i 's/${TELEGRAM_CHAT_ID}/CHAT_ID/' /data/workspace/skills/phoenix-strategy/runtime.yaml`
5. Install runtime: `openclaw senpi runtime create --path /data/workspace/skills/phoenix-strategy/runtime.yaml`
6. Verify runtime installed: `openclaw senpi runtime list`
7. Check runtime health: `openclaw senpi status` — must show healthy
8. Create scanner cron (2 min, main)
9. Write `config/bootstrap-complete.json`
10. Send: "🔥 PHOENIX v1.0.1 online. Hunting divergences. Silence = no signal."

If bootstrap exists, still verify runtime, scanner cron, and health on every session start:
- `openclaw senpi runtime list` — runtime running
- `openclaw senpi status` — healthy
- `openclaw crons list` — scanner cron present, no DSL cron

---

## Risk Management

| Rule | Value |
|---|---|
| Max positions | 3 |
| Max entries/day | 6 |
| Leverage | 10x |
| Daily loss limit | 10% |
| Per-asset cooldown | 2 hours |
| XYZ equities | Banned |
| Min divergence ratio | 5x |
| Min SM traders | 10 |
| Min score | 7 |

---

## Notification Policy

**ONLY alert:** Position OPENED, position CLOSED (P&L + reason), critical error.

**NEVER alert:** Scanner found nothing, any reasoning.

---

## Files

| File | Purpose |
|---|---|
| `scripts/phoenix-scanner.py` | Contribution velocity divergence scanner |
| `scripts/phoenix_config.py` | Config helper with MCP, state I/O |
| `config/phoenix-config.json` | Config with wallet, strategy ID |
| `runtime.yaml` | Runtime YAML for DSL plugin (position tracker + exit engine) |

---

## License

MIT — Built by Senpi (https://senpi.ai).
Source: https://github.com/Senpi-ai/senpi-skills
