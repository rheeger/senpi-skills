---
name: wolverine-strategy
description: >-
  WOLVERINE v2.0 — HYPE alpha hunter. Entry-only scanner, DSL-exit-only
  architecture. v1.1 lost -22.7% because the scanner's thesis exit chopped
  25/27 trades before DSL could manage them. v2.0 removes thesis exit entirely.
  Scanner decides entries (score 8+, 4H/1H aligned, SM consensus). DSL manages
  all exits (wide Phase 1 for HYPE volatility, trailing tiers starting at +15% ROE).
  Leverage lowered to 7x. Max 4 entries/day. 3-hour cooldown between entries.
license: MIT
metadata:
  author: jason-goldberg
  version: "2.0"
  platform: senpi
  exchange: hyperliquid
---

# 🦡 WOLVERINE v2.0 — HYPE Alpha Hunter

Scanner enters. DSL exits. The scanner NEVER re-evaluates open positions.

---

## ⛔ CRITICAL AGENT RULES

### RULE 1: Install path is `/data/workspace/skills/wolverine-strategy/`

### RULE 2: THE SCANNER DOES NOT EXIT POSITIONS

This is the single most important rule. When the scanner output contains `"_v2_no_thesis_exit": true` and the note says "DSL manages exit. Scanner does NOT re-evaluate," that means **DO NOT close, modify, or re-evaluate the open position for any reason.** The DSL cron is the ONLY mechanism that can close positions.

v1.1 lost -22.7% because the scanner kept killing positions via "thesis exit" — 25 of 27 trades were chopped by the scanner before DSL could manage them. On HYPE, which wicks 5-10% ROE routinely, the scanner saw every wick as "thesis invalidation" and cut winners that would have run to +30%.

**If you close a position because "the thesis changed" or "SM flipped" or "the 4H trend broke," you are violating this rule and will bleed exactly like v1.1 did.**

### RULE 3: MAX 1 POSITION at a time

Only one HYPE position at a time. Check clearinghouse before every entry.

### RULE 4: Scanner output is AUTHORITATIVE

Leverage, margin, direction — use exactly what the scanner says.

### RULE 5: Write dslState directly — include wallet address

Write the scanner's `dslState` block directly to the state file. It already contains `wallet` and `strategyWalletAddress`. Do NOT strip these fields.

### RULE 6: Verify BOTH crons on every session start

Scanner cron (3 min) and DSL cron (3 min) must both be running.

### RULE 7: Never modify parameters

### RULE 8: 3-hour cooldown between entries

After any position close (DSL floor, timeout, trailing stop, stagnation TP), wait 3 hours before the next entry. This prevents revenge trading after a loss.

---

## What Changed From v1.1

| Setting | v1.1 | v2.0 | Why |
|---|---|---|---|
| Scanner thesis exit | ENABLED (killed 25/27 trades) | **REMOVED** | Was chopping winners |
| DSL authority | Shared with scanner | **DSL-ONLY exits** | One exit mechanism, no conflicts |
| Entry score threshold | ~5 (effectively) | **8** | Fewer, higher conviction entries |
| 4H/1H alignment | Optional | **REQUIRED** | Both timeframes must agree |
| Leverage | 10x | **7x** | More room to breathe on HYPE |
| Max daily entries | Unlimited | **4** | Patience is the edge |
| Cooldown | 120 min | **180 min** | 3 hours, prevent revenge trading |
| Phase 2 trigger | 7% ROE | **15% ROE** | Don't trail until a real move |
| First trailing tier | 7% trigger, 40% lock | **15% trigger, 30% lock** | Wide breathing room |

---

## The Thesis

HYPE moves 2-4% routinely. At 7x leverage, that's 14-28% ROE. The edge is:
1. Enter only when SM consensus + price momentum + contribution acceleration all align (score 8+)
2. Let DSL manage the position through HYPE's normal volatility
3. Wide Phase 1 floor (-20% ROE) survives the wicks that killed v1.1 entries
4. Trailing tiers don't engage until +15% ROE — no premature profit locking
5. When HYPE runs, it runs hard. One +30% ROE trade pays for 3 losing trades at -10%

**v1.1 proof:** Trade #6 hit +29.92% ROE (+$112) when the scanner accidentally let it run. That single trade was worth more than all other 13 winners combined.

---

## DSL Configuration (Wide for HYPE)

### Phase 1 (Entry Protection)
| Parameter | Value | Why |
|---|---|---|
| Absolute floor | -20% ROE | At 7x, allows ~2.85% adverse price move |
| Hard timeout | 120 min | 2 hours to develop thesis |
| Weak peak cut | 60 min | 1 hour at weak profit before cutting |
| Dead weight cut | 45 min | 45 min flat before cutting |
| Consecutive breaches | 3 | Survives single wicks |

### Phase 2 (Profit Trailing)
| Trigger ROE | Lock % of Peak | Breaches | Note |
|---|---|---|---|
| +15% | 30% | 3 | Initial pop — wide room |
| +25% | 50% | 2 | Quarter-way up, lock half |
| +40% | 65% | 1 | Solid profit |
| +60% | 75% | 1 | Deep run |
| +80% | 85% | 1 | Infinite trail |

### Stagnation TP
If ROE >= 15% and high water hasn't moved for 60 minutes, take profit.

---

## Cron Setup

Scanner cron (3 minutes, main session):
```
python3 /data/workspace/skills/wolverine-strategy/scripts/wolverine-scanner.py
```

DSL cron (3 minutes, isolated session):
```
python3 /data/workspace/skills/dsl-dynamic-stop-loss/scripts/dsl-v5.py --state-dir /data/workspace/skills/wolverine-strategy/state
```

---

## Bootstrap Gate

On EVERY session start, check `config/bootstrap-complete.json`. If missing:
1. Verify Senpi MCP
2. Create scanner cron (3 min, main) and DSL cron (3 min, isolated)
3. Verify BOTH crons `status: ok`
4. Write `config/bootstrap-complete.json`
5. Send: "🦡 WOLVERINE v2.0 online. HYPE hunter. Entry-only scanner. DSL manages all exits. Waiting for score 8+ setup."

---

## Notification Policy

**ONLY alert:** Position OPENED (direction, score, reasons, leverage), Position CLOSED BY DSL (P&L, close reason, duration), critical error.

**NEVER alert:** Scanner found no signal, scanner sees open position and is not re-evaluating, DSL routine checks, any reasoning about whether to exit an open position.

---

## Expected Behavior

| Metric | Expected |
|---|---|
| Entries/day | 0-3 (some zero-trade days) |
| Position duration | 30 min to 12+ hours |
| Win rate | ~35-40% |
| Avg winner | +15% to +30% ROE |
| Avg loser | -10% to -20% ROE (Phase 1 cuts) |
| Net edge | Winners 2-3x larger than losers |

**Long periods of silence are expected.** HYPE must have SM consensus, 4H/1H alignment, contribution acceleration, AND score 8+ to enter. That's rare. The patience IS the edge.

---

## Files

| File | Purpose |
|---|---|
| `scripts/wolverine-scanner.py` | Entry-only scanner. NO thesis exit. |
| `scripts/wolverine_config.py` | Config helper |
| `config/wolverine-config.json` | All parameters |

---

## License

MIT — Built by Senpi (https://senpi.ai).
