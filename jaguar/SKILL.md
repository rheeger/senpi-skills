---
name: jaguar-strategy
description: >-
  JAGUAR v2.0 — Striker-Only. Stalker and Hunter removed. Pyramiding removed.
  v1.0 lost -29.3% across 5 trades. 4 of 5 had broken DSL (missing size field
  in state file). v2.0 fixes DSL state generation with wallet+size fields,
  reduces leverage to 7x, and focuses exclusively on STRIKER signals (violent
  FIRST_JUMP explosions, score 9+, volume 1.5x).
license: MIT
metadata:
  author: jason-goldberg
  version: "2.0"
  platform: senpi
  exchange: hyperliquid
---

# 🐆 JAGUAR v2.0 — Striker-Only

Violent explosions only. DSL manages exits.

---

## ⛔ CRITICAL AGENT RULES

### RULE 1: Install path is `/data/workspace/skills/jaguar-strategy/`

### RULE 2: THE SCANNER DOES NOT EXIT POSITIONS

### RULE 3: MAX 2 POSITIONS at a time

### RULE 4: Scanner output is AUTHORITATIVE

### RULE 5: Write dslState directly — MUST update 'size' from clearinghouse

After opening a position, read `strategy_get_clearinghouse_state` to get the
actual position size (`abs(szi)`). Update the DSL state file's `size` field
with this value. The scanner sets `size: null` as a placeholder — the agent
MUST fill it in. **This was the exact bug that broke 4 of 5 trades in v1.0.**

### RULE 6: Verify BOTH crons on every session start

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

## Cron Setup

Scanner cron (3 min, main):
```
python3 /data/workspace/skills/jaguar-strategy/scripts/jaguar-scanner.py
```

DSL cron (3 min, isolated):
```
python3 /data/workspace/skills/dsl-dynamic-stop-loss/scripts/dsl-v5.py --state-dir /data/workspace/skills/jaguar-strategy/state
```

---

## DSL Configuration

| Parameter | Value |
|---|---|
| Phase 1 floor | -20% ROE (at 7x = 2.86% price move) |
| Phase 1 timeout | 45 min |
| Dead weight cut | 12 min |
| Weak peak cut | 25 min |
| Phase 2 trigger | +7% ROE |
| Consecutive breaches | 3 |
| Trailing tiers | 7%/40%, 12%/55%, 15%/75%, 20%/85% |

---

## License

MIT — Built by Senpi (https://senpi.ai).
