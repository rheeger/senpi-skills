---
name: bald-eagle-strategy
description: >-
  BALD EAGLE v2.0 — XYZ Alpha Hunter. Trades high-liquidity XYZ assets on
  Hyperliquid: commodities (GOLD, SILVER, CL, BRENTOIL), indices (SP500, XYZ100),
  and select equities (TSLA, NVDA). Spread gate rejects illiquid assets.
  Leverage capped at 7x (v1.0 used 20x and got liquidated).
  DSL manages all exits. No thesis exit.
license: MIT
metadata:
  author: jason-goldberg
  version: "2.0"
  platform: senpi
  exchange: hyperliquid
---

# 🦅 BALD EAGLE v2.0 — XYZ Alpha Hunter

The only Senpi agent trading commodities, indices, and equities on Hyperliquid.

---

## ⛔ CRITICAL AGENT RULES

### RULE 1: Install path is `/data/workspace/skills/bald-eagle-strategy/`

### RULE 2: THE SCANNER DOES NOT EXIT POSITIONS

### RULE 3: SPREAD GATE IS THE FILTER — NOT A WHITELIST

All 54 XYZ assets are eligible. The live spread gate (> 0.1% = rejected)
automatically filters out illiquid garbage. No static whitelist needed.
SNDK is the only hard ban.

### RULE 4: MAX 3 POSITIONS at a time

### RULE 5: Write dslState directly — MUST update 'size' from clearinghouse

### RULE 6: Verify BOTH crons on every session start

### RULE 7: Never modify parameters. Never increase leverage above 7x.

### RULE 8: 120-minute per-asset cooldown

---

## v1.0 Post-Mortem

- 6 trades, 5 had broken DSL (state files in wrong directory)
- CL LONG at 20x: LIQUIDATED at -56.4% ROE, ran 3.7 hours orphaned
- GOLD SHORT at 20x: ran 15 hours unprotected, closed manually at -1.4%
- BRENTOIL LONG at 20x: ran 3.2 hours unprotected, closed manually at -21.3%
- 86% of losses ($246 of $286) came from DSL infrastructure failure

## What Changed

| v1.0 | v2.0 |
|---|---|
| No asset whitelist | GOLD, SILVER, CL, BRENTOIL, SP500, XYZ100, TSLA, NVDA |
| No spread check | Spread gate: rejects > 0.1% live spread |
| 20x leverage | 7x leverage |
| DSL state missing wallet | Wallet + strategyId + size included |
| No entry limits | 3 entries/day max |
| Thesis exit active | Removed — DSL manages all exits |

---

## Whitelisted Assets (Live Data)

| Asset | Type | 24H Volume | Spread | Max Lev |
|---|---|---|---|---|
| SILVER | Commodity | $487M | 0.007% | 25x |
| CL | Commodity | $375M | 0.043% | 20x |
| BRENTOIL | Commodity | $285M | 0.040% | 20x |
| SP500 | Index | $175M | TBD | 50x |
| XYZ100 | Index | $158M | TBD | 30x |
| GOLD | Commodity | $101M | 0.002% | 25x |
| TSLA | Equity | $17M | 0.034% | 10x |
| NVDA | Equity | $15M | 0.069% | 20x |

---

## Cron Setup

Scanner (5 min, main):
```
python3 /data/workspace/skills/bald-eagle-strategy/scripts/eagle-scanner.py
```

DSL (3 min, isolated):
```
python3 /data/workspace/skills/dsl-dynamic-stop-loss/scripts/dsl-v5.py --state-dir /data/workspace/skills/bald-eagle-strategy/state
```

---

## DSL Configuration

| Parameter | Value |
|---|---|
| Phase 1 floor | -15% ROE (at 7x = 2.14% price) |
| Phase 1 timeout | 45 min |
| Phase 1 retrace | 0.08 (8% ROE) |
| Dead weight cut | 12 min |
| Weak peak cut | 20 min |
| Trailing tiers | 7%/40%, 12%/55%, 20%/70%, 30%/80% |

---

## Risk

| Rule | Value |
|---|---|
| Max positions | 3 |
| Max entries/day | 6 |
| Leverage | 7x (capped) |
| Spread gate | > 0.1% = rejected |
| Per-asset cooldown | 90 min |
| Daily loss limit | 10% |
| SNDK | Banned |

---

## Files

| File | Purpose |
|---|---|
| `scripts/eagle-scanner.py` | XYZ SM scanner with spread gate + conviction scoring |
| `scripts/eagle_config.py` | Config helper (MCP, state, market hours, cooldowns) |
| `config/bald-eagle-config.json` | Wallet, strategy ID |

---

## License

MIT — Built by Senpi (https://senpi.ai).
