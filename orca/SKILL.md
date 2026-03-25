---
name: orca-strategy
description: >-
  ORCA v1.3 — Dual-mode scanner (Stalker + Striker). The clean experiment:
  does Stalker add value on top of Striker? Roach = Striker only (+8.2%).
  Orca v1.3 = both modes with hardened infrastructure. Hunter removed (0 trades).
  Pyramiding removed. Thesis exit removed. DSL manages all exits.
  Max 8 entries/day to prevent fee bleed.
license: MIT
metadata:
  author: jason-goldberg
  version: "1.3"
  platform: senpi
  exchange: hyperliquid
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

### RULE 5: Write dslState directly — MUST update 'size' from clearinghouse

### RULE 6: Verify BOTH crons on every session start

### RULE 7: Never modify parameters. Never build an Auto-Scaler.

### RULE 8: 120-minute per-asset cooldown

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
| Crons kept dying silently | Hardened cron setup with verification |
| State files in wrong directory | Single canonical state dir |
| Self-healing loop creating more bugs | No self-healing — if state breaks, report it |
| Hunter mode (0 trades) | Removed |
| Pyramiding (never triggered) | Removed |
| No entry cap (30 trades/day) | 8 entries/day max |
| 10x leverage | 7x leverage |
| DSL state missing wallet + size | Both included |
| Thesis exit active | Removed — DSL manages all exits |

---

## Cron Setup

Scanner (3 min, main):
```
python3 /data/workspace/skills/orca-strategy/scripts/orca-scanner.py
```

DSL (3 min, isolated):
```
python3 /data/workspace/skills/dsl-dynamic-stop-loss/scripts/dsl-v5.py --state-dir /data/workspace/skills/orca-strategy/state
```

---

## DSL Configuration (Conviction-Tiered)

| Score | Floor | Timeout | Weak Peak | Dead Weight |
|---|---|---|---|---|
| 6-7 | -18% ROE | 25 min | 12 min | 8 min |
| 8-9 | -25% ROE | 45 min | 20 min | 15 min |
| 10+ | -30% ROE | 60 min | 30 min | 20 min |

Trailing: 7%/40%, 12%/55%, 15%/75%, 20%/85%.

---

## Risk

| Rule | Value |
|---|---|
| Max positions | 3 |
| Max entries/day | 8 |
| Leverage | 7x |
| Per-asset cooldown | 120 min |
| Daily loss limit | 10% |
| XYZ | Banned |

---

## License

MIT — Built by Senpi (https://senpi.ai).
