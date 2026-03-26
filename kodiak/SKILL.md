---
name: kodiak-strategy
description: >-
  KODIAK v2.0 — SOL alpha hunter with position lifecycle. Thesis exit removed.
  DSL manages all exits. DSL state includes wallet + strategyWalletAddress +
  strategyId + size. Leverage capped at 7x. Retrace widened to 0.08.
  v1.1.1's SOL SHORT ran 13 hours unprotected due to missing wallet fields —
  v2.0 prevents this.
license: MIT
metadata:
  author: jason-goldberg
  version: "2.0"
  platform: senpi
  exchange: hyperliquid
  base_skill: grizzly-v2.0
---

# 🐻 KODIAK v2.0 — SOL Alpha Hunter

One asset. Every signal. Scanner enters. DSL exits.

---

## ⛔ CRITICAL AGENT RULES

### RULE 1: Install path is `/data/workspace/skills/kodiak-strategy/`

### RULE 2: THE SCANNER DOES NOT EXIT POSITIONS

When the scanner sees an active SOL position, it outputs NO_REPLY. DSL is the
ONLY exit mechanism. v1.1.1 had a thesis exit that chopped positions before
DSL could trail them. v2.0 removes it entirely.

### RULE 3: MAX 1 POSITION — SOL only

### RULE 4: Scanner output is AUTHORITATIVE

### RULE 5: Write dslState directly — MUST update 'size' from clearinghouse

The scanner provides a `dslState` block with `wallet`, `strategyWalletAddress`,
`strategyId`, and `size: null`. After entry fills, read clearinghouse to get
actual size (`abs(szi)`) and update the state file. **This was the exact bug
that left a +$134 winner unprotected for 13 hours in v1.1.1.**

### RULE 6: Verify BOTH crons on every session start

### RULE 7: Never modify parameters. Never increase leverage above 7x.

### RULE 8: 120-minute cooldown after consecutive losses

---

## What Changed From v1.1.1

| v1.1.1 | v2.0 |
|---|---|
| Thesis exit active in RIDING mode | **Removed** — DSL manages all exits |
| DSL state missing wallet + size | **All fields included** |
| Leverage 10-12x | **Capped at 7x** |
| Retrace 0.03 (3% ROE = 0.3% price at 10x) | **0.08 (8% ROE = 1.14% price at 7x)** |
| `strategy_id` discarded in run() | **Captured and passed to DSL builder** |
| SOL SHORT ran 13h unprotected | **Every position protected from second 1** |

---

## v1.1.1 Proof of Concept

Kodiak's best trade: SOL SHORT, entry $90.36, DSL trailed to Tier 4 (+44% ROE),
exit at $85.86, realized **+$134** profit. The scanner found the setup. DSL
managed the exit perfectly — locked 85% of peak, gave back only $3 from top.

The problem: DSL was manually patched onto this trade 13 hours after entry
because the state file was missing wallet fields. v2.0 fixes this permanently.

---

## The Three-Mode Lifecycle

### MODE 1 — HUNTING (default)

Scan SOL every 3 minutes. All signals must align (4h trend, 1h momentum, SM,
funding, OI, volume). Score 10+ to enter. When a position opens, switch to MODE 2.

### MODE 2 — RIDING

Active position. **DSL manages the exit. Scanner outputs NO_REPLY.**
The scanner does NOT re-evaluate the thesis. It does NOT close positions.
DSL High Water trails the position through Phase 1 protection and Phase 2
trailing tiers. When DSL closes the position → switch to MODE 3.

### MODE 3 — STALKING

DSL locked profits. Watch for a reload opportunity. ALL reload conditions
must pass: fresh momentum impulse, OI stable, volume present, funding not
crowded, SM still aligned, 4h trend intact.

If reload fires → re-enter same direction, switch to MODE 2.
If kill conditions trigger → reset to MODE 1.

---

## Cron Setup

Scanner (3 min, main):
```
python3 /data/workspace/skills/kodiak-strategy/scripts/kodiak-scanner.py
```

DSL (3 min, isolated):
```
python3 /data/workspace/skills/dsl-dynamic-stop-loss/scripts/dsl-v5.py --state-dir /data/workspace/skills/kodiak-strategy/state
```

---

## DSL Configuration (Conviction-Tiered)

| Score | Floor | Timeout | Weak Peak | Dead Weight |
|---|---|---|---|---|
| 8-9 | -25% ROE | 45 min | 20 min | 15 min |
| 10-11 | -30% ROE | 60 min | 30 min | 20 min |
| 12+ | -35% ROE | 90 min | 45 min | 30 min |

Phase 1 retrace: 0.08 (8% ROE). Trailing tiers: 7%/40%, 12%/55%, 15%/75%, 20%/85%.

---

## Risk

| Rule | Value |
|---|---|
| Max positions | 1 (SOL only) |
| Max leverage | 7x |
| Phase 1 retrace | 0.08 |
| Daily loss limit | 10% |
| Cooldown | 120 min after 3 consecutive losses |
| Stagnation TP | 10% ROE stale 45 min |

---

## Files

| File | Purpose |
|---|---|
| `scripts/kodiak-scanner.py` | SOL thesis builder + stalk/reload + DSL state generation |
| `scripts/kodiak_config.py` | Config helper (MCP, state, cooldowns) |
| `config/kodiak-config.json` | Wallet, strategy ID, configurable variables |

---

## License

MIT — Built by Senpi (https://senpi.ai).
Source: https://github.com/Senpi-ai/senpi-skills
