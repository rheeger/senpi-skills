---
name: cheetah-strategy
description: >-
  CHEETAH v2.0 — The Ultimate HYPE Predator. Single asset, every signal source,
  maximum patience. SM commitment required (80%+ one direction). BTC is a booster,
  never a gate. Wide DSL tiers for HYPE's 5-10% intraday wicks.
  DSL exit managed by plugin runtime via runtime.yaml.
license: MIT
metadata:
  author: jason-goldberg
  version: "2.0"
  platform: senpi
  exchange: hyperliquid
  requires:
    - senpi-trading-runtime
---

# 🐆 CHEETAH v2.0 — The Ultimate HYPE Predator

One asset. Every signal. Strike when SM is committed.

---

## ⛔ CRITICAL AGENT RULES

### RULE 1: Install path is `/data/workspace/skills/cheetah-strategy/`

### RULE 2: THE SCANNER DOES NOT EXIT POSITIONS

When the scanner sees an active HYPE position, it outputs NO_REPLY. DSL is the
ONLY exit mechanism. v1.0 had thesis exit active. v2.0 removes it entirely.

### RULE 3: MAX 1 POSITION — HYPE only

### RULE 4: Verify runtime is installed on every session start

Run `openclaw senpi runtime list`. Runtime must be listed and healthy.
Run `openclaw senpi status` to confirm.

### RULE 5: Never modify parameters. Never increase leverage above 7x.

### RULE 6: MAX 3 ENTRIES PER DAY

### RULE 7: 120-minute cooldown between trades

---

## Why HYPE Is Different

HYPE is Hyperliquid's native token. It moves on protocol narratives, not just
crypto macro. Lower BTC correlation. Routinely wicks 5-10% intraday then reverses.
SM positioning is often extreme (100% one direction). Funding swings dramatically.

Cheetah is built specifically for these characteristics:
- **SM commitment gate:** SM must be 80%+ one direction (not just "aligned")
- **BTC is a booster, never a gate:** HYPE moves independently
- **Wide DSL tiers:** lock only 15% at +5% ROE because HYPE wicks hard
- **No time-based cuts:** HYPE trends develop over 4-12 hours
- **7x max leverage:** HYPE is volatile enough without amplification

---

## Scoring System (14 points max)

| Signal | Points | Required? |
|---|---|---|
| SM commitment (3-15%+ concentration) | 1-4 | **Yes (min 3% + 15 traders)** |
| 4H trend aligned with SM | 1-2 | **Yes (hard block if opposing)** |
| 1H confirms direction | 0-1 | No (bonus) |
| Contribution velocity accelerating | 0-2 | No |
| Funding confirms direction | 0-2 | No |
| Volume surge (1.5x+) | 0-1 | No |
| BTC confirms direction | 0-1 | No (booster only) |
| Rank sweet spot (#5-20) | 0-1 | No |

**Min score to enter: 8.** Ensures at least SM + trend + 2 confirming signals.

---

## Exit Management

DSL exit handled by plugin runtime via `runtime.yaml`.

**Entry flow:**
1. Scanner outputs signal (score 8+, SM committed, 4H aligned)
2. Verify no existing HYPE position
3. Call `create_position`
4. `position_tracker` detects the new position automatically
5. Plugin DSL applies trailing stop-loss protection

**Monitor:**
- `openclaw senpi dsl positions` — DSL-tracked positions
- `openclaw senpi dsl inspect HYPE` — full position details
- `openclaw senpi status` — runtime health

---

## Runtime Setup

**Step 1:** Set wallet:
```bash
sed -i 's/${WALLET_ADDRESS}/<STRATEGY_WALLET>/' /data/workspace/skills/cheetah-strategy/runtime.yaml
```

**Step 2:** Set telegram:
```bash
sed -i 's/${TELEGRAM_CHAT_ID}/<CHAT_ID>/' /data/workspace/skills/cheetah-strategy/runtime.yaml
```

**Step 3:** Install:
```bash
openclaw senpi runtime create --path /data/workspace/skills/cheetah-strategy/runtime.yaml
```

**Step 4:** Verify:
```bash
openclaw senpi runtime list
openclaw senpi status
```

---

## Bootstrap Gate

On EVERY session start, check `config/bootstrap-complete.json`. If missing:
1. Read senpi-trading-runtime skill
2. Verify Senpi MCP
3. Set wallet and telegram in runtime.yaml
4. Install runtime: `openclaw senpi runtime create --path /data/workspace/skills/cheetah-strategy/runtime.yaml`
5. Verify: `openclaw senpi runtime list` and `openclaw senpi status`
6. Create scanner cron (3 min, main)
7. Write `config/bootstrap-complete.json`
8. Send: "🐆 CHEETAH v2.0 online. Hunting HYPE. Silence = no conviction."

If bootstrap exists, verify runtime + status + scanner cron on every session start.

---

## DSL Configuration (HYPE-Specific)

| Setting | Value | Why |
|---|---|---|
| Hard timeout | 180 min | HYPE trends develop over hours |
| Weak peak cut | **Disabled** | HYPE wicks kill patience strategies |
| Dead weight cut | **Disabled** | Same reason |
| Max loss | 25% ROE | At 7x = 3.6% price move |
| Retrace | 8% ROE | Wide for HYPE's volatility |
| Consecutive breaches | 3 | Survive HYPE's violent wicks |

**Phase 2 Tiers (HYPE-specific wide locks):**

| Trigger | Lock | Why |
|---|---|---|
| +5% ROE | 15% | Barely lock — HYPE wicks through +5% constantly |
| +10% | 30% | Starting to lock — the move is real |
| +15% | 50% | Half locked — meaningful trend |
| +20% | 65% | Locked in — strong runner |
| +30% | 80% | Hard lock — exceptional move |
| +50% | 90% | Maximum lock — generational trade |

---

## Risk

| Rule | Value |
|---|---|
| Max positions | 1 (HYPE only) |
| Max leverage | 7x |
| Max entries/day | 3 |
| Cooldown | 120 min |
| Min score | 8 |

---

## Files

| File | Purpose |
|---|---|
| `scripts/cheetah-scanner.py` | HYPE predator scanner — multi-signal scoring |
| `scripts/cheetah_config.py` | Config helper (MCP, state, cooldowns) |
| `config/cheetah-config.json` | Wallet, strategy ID |
| `runtime.yaml` | Runtime YAML for DSL plugin (HYPE-specific wide tiers) |

---

## License

MIT — Built by Senpi (https://senpi.ai).
