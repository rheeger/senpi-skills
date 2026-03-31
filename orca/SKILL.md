---
name: orca-strategy
description: >-
  ORCA v1.3 — Dual-mode scanner (Stalker + Striker). The clean experiment:
  does Stalker add value on top of Striker? Roach = Striker only (+8.2%).
  Orca v1.3 = both modes with hardened infrastructure. Hunter removed (0 trades).
  Pyramiding removed. Thesis exit removed. DSL manages all exits.
  Max 8 entries/day to prevent fee bleed.
  DSL exit managed by plugin runtime via runtime.yaml.
license: MIT
metadata:
  author: jason-goldberg
  version: "2.0"
  platform: senpi
  exchange: hyperliquid
  based_on: orca-v1.1.1
  config_source: orca-v1.1.1-plus-fox-trade-data-lessons
  requires:
    - senpi-trading-runtime
---

# 🐋 ORCA v1.3 — Dual-Mode Scanner (Stalker + Striker)

The experiment: does Stalker add value, or is Striker-only the answer?

---

## ⛔ CRITICAL AGENT RULES

### RULE 1: Install path is `/data/workspace/skills/orca-strategy/`

### RULE 2: THE SCANNER DOES NOT EXIT POSITIONS

### RULE 3: MAX 3 POSITIONS at a time

### RULE 4: MAX 8 ENTRIES PER DAY — non-negotiable

v1.1 was doing 30 trades/day and bleeding $80+/day in fees despite positive
gross P&L. 8 entries × ~$4 fees = $32/day max fee exposure.

### RULE 5: Verify runtime is installed on every session start

Run `openclaw senpi runtime list`. Runtime must be listed. The position tracker and DSL exit are handled by the plugin runtime.

### RULE 6: Never retry timed-out position creation

If `create_position` times out, check clearinghouse state. If position exists, the position tracker will pick it up automatically. If not, wait for next scan.

### RULE 7: Never modify your own configuration

Do not adjust leverage, margin, entry caps, or scoring thresholds.

### RULE 8: Record Stalker results for streak tracking

After every Stalker position closes, call `record_stalker_result(tc, is_win)` from orca_config.py. The scanner uses this to detect losing streaks and temporarily raise the entry bar.

### RULE 9: 120-minute per-asset cooldown

---

## Experiment Design

| Agent | Strategy | What It Tests |
|---|---|---|
| Roach | Striker only | Pure explosion signals |
| Orca v1.3 | Stalker + Striker | Does accumulation detection add value? |

If v1.3 outperforms Roach, Stalker stays in the architecture.
If Roach wins, Stalker is removed permanently from all skills.

---

## What Changed

| v1.2 | v1.3 |
|---|---|
| Crons kept dying silently | Hardened setup with runtime verification |
| State files in wrong directory | Single canonical state dir |
| Self-healing loop creating more bugs | No self-healing — if state breaks, report it |
| Hunter mode (0 trades) | Removed |
| Pyramiding (never triggered) | Removed |
| No entry cap (30 trades/day) | 8 entries/day max |
| 10x leverage | 7x leverage |
| Thesis exit active | Removed — DSL manages all exits |

---

## Entry Modes

### MODE A — STALKER (Accumulation) — Score >= 7
- SM rank climbing steadily over 3+ consecutive scans
- Total climb >= 8 ranks (was 5 in v1.1.1)
- Contribution building each scan
- 4H trend aligned
- **v1.2 streak gate:** If last 3 Stalker trades were all losses, minScore temporarily raised to 9

### MODE B — STRIKER (Explosion) — Score >= 9, min 4 reasons
- FIRST_JUMP or IMMEDIATE_MOVER (10+ rank jump from #25+)
- Rank jump >= 15 OR velocity > 15
- Raw volume >= 1.5x of 6h average
- Unchanged from v1.1.1

---

## Exit Management

DSL exit is handled by the plugin runtime via `runtime.yaml`. The `position_tracker` scanner auto-detects position opens/closes on-chain. See `runtime.yaml` for configuration details.

**Entry flow:**
1. Scanner outputs signal
2. Verify positions < 3 (check clearinghouse state)
3. Verify exchange max leverage >= 7 for this asset
4. Call `create_position` with coin, direction, leverage, margin
5. Send ONE notification: position opened
6. `position_tracker` detects the new position automatically
7. Plugin DSL monitor applies trailing stop-loss protection

**Monitor positions:**
- `openclaw senpi dsl positions` — list all DSL-tracked positions
- `openclaw senpi dsl inspect <ASSET>` — full position details

**On position close:**
8. Record result: call `record_stalker_result(tc, is_win)` if the position was a Stalker entry

---

## Runtime Setup

**Step 1:** Set your strategy wallet address in runtime.yaml:
```bash
sed -i 's/${WALLET_ADDRESS}/<STRATEGY_WALLET_ADDRESS>/' /data/workspace/skills/orca-strategy/runtime.yaml
```
Replace `<STRATEGY_WALLET_ADDRESS>` with the actual wallet address.

**Step 2:** Set telegram chat ID for notifications:
```bash
sed -i 's/${TELEGRAM_CHAT_ID}/<CHAT_ID>/' /data/workspace/skills/orca-strategy/runtime.yaml
```
Replace `<CHAT_ID>` with the actual Telegram chat ID.

**Step 3:** Install the runtime:
```bash
openclaw senpi runtime create --path /data/workspace/skills/orca-strategy/runtime.yaml
```

**Step 4:** Verify:
```bash
openclaw senpi runtime list
```

---

## Bootstrap Gate

On EVERY session start, check `config/bootstrap-complete.json`. If missing:
1. Read the senpi-trading-runtime skill: `cat /data/workspace/skills/senpi-trading-runtime/SKILL.md` — this provides all CLI commands for runtime management and DSL position inspection.
2. Verify Senpi MCP
3. Set wallet in runtime.yaml: `sed -i 's/${WALLET_ADDRESS}/ACTUAL_ADDRESS/' /data/workspace/skills/orca-strategy/runtime.yaml`
4. Set Telegram in runtime.yaml: `sed -i 's/${TELEGRAM_CHAT_ID}/CHAT_ID/' /data/workspace/skills/orca-strategy/runtime.yaml`
5. Install runtime: `openclaw senpi runtime create --path /data/workspace/skills/orca-strategy/runtime.yaml`
6. Verify runtime installed: `openclaw senpi runtime list`
7. Remove old DSL cron (if upgrading): run `openclaw crons list`, delete any cron containing `dsl-v5.py` via `openclaw crons delete <id>`
8. Create scanner cron (90s, main)
9. Write `config/bootstrap-complete.json`
10. Send: "🐋 ORCA v1.3 online. Stalker + Striker experiment. Max 8 entries/day. DSL managed by plugin runtime. Silence = no conviction."

If bootstrap exists, still verify runtime and scanner cron on every session start.

---

## Risk

| Rule | Value | Why |
|---|---|---|
| Max positions | 3 | Concentration > diversification |
| Max entries/day | 8 | Prevents fee bleed |
| Leverage | 7x | Sub-7x can't overcome fees; 15x blows up |
| Daily loss limit | 10% | Proven across 30 agents |
| Per-asset cooldown | 120 min | PAXG double-entry lesson |
| XYZ equities | Banned | Net negative across every agent |
| Stalker streak gate | 3 consecutive Stalker losses → minScore 9 | Prevents weak-peak bleed |

---

## Notification Policy

**ONLY alert:** Position OPENED, position CLOSED (with P&L and reason), streak gate activated/deactivated, risk guardian triggered, critical error.

**NEVER alert:** Scanner ran with no signals, any reasoning.

---

## Files

| File | Purpose |
|---|---|
| `scripts/orca-scanner.py` | Dual-mode scanner with Fox's lessons + streak gate |
| `scripts/orca_config.py` | Config helper with stalkerResults tracking |
| `config/orca-config.json` | Config with v1.2 Stalker thresholds |
| `runtime.yaml` | Runtime config for plugin (DSL exit + position tracker) |

---

## License

MIT — Built by Senpi (https://senpi.ai).
