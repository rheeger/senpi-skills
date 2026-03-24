# MANTIS v3.0 — DSL Implementation

## Overview

MANTIS v3.0 is a **dual-mode** emerging movers scanner with one experimental tweak:
- **STALKER**: SM accumulating over 3+ scans, score 7+. **Contrib accel threshold raised to 0.003** (was 0.001). CONTRIB_POSITIVE tier eliminated.
- **STRIKER**: Violent first-jump + volume ≥ 1.5x, score 9+. Enter the explosion.

**MANTIS's experiment**: Only genuine acceleration (CONTRIB_ACCEL > 0.003) earns contribution points. Fox v1.0 data showed trades with CONTRIB_POSITIVE (weak velocity, 0 < delta ≤ 0.001) were noise — SM interest barely growing. The +1 tier is eliminated entirely.

The DSL exit engine is identical to ORCA, FOX, and ROACH.

## DSL Two-Phase Model

### Phase 1 — Capital Protection
Active from position open until ROE reaches the first tier trigger (7%).

| Parameter | Value | Source |
|---|---|---|
| Retrace threshold | 3% ROE | `retraceThreshold: 0.03` |
| Consecutive breaches required | 3 | Fox's #1 bug fix |
| Absolute floor | -18% ROE (score≥6) | `absoluteFloorRoe: -18` |

**Time-based cuts** (conviction-scaled, score≥6 defaults):

| Cut | Interval | Behavior |
|---|---|---|
| Hard timeout | 25 min | Close regardless of P&L |
| Weak peak cut | 12 min | Close if peak ROE < 3% and current < peak |
| Dead weight cut | 8 min | Close if position never went positive |

**Floor computation** (Phase 1):
```
trailing_floor = high_water_price × (1 - retrace_threshold / 100 / leverage)
absolute_floor = entry_price × (1 - |absoluteFloorRoe| / 100 / leverage)
effective_floor = max(trailing_floor, absolute_floor)  # for LONG
```

### Phase 2 — Profit Protection
Activated when ROE hits the first tier trigger (7% → `phase2_trigger_tier: 0`).

| Parameter | Value |
|---|---|
| Retrace threshold | 1.5% ROE |
| Consecutive breaches required | 2 |

**Tier progression**:

| Tier | Trigger ROE | Lock HW % | Breaches Required |
|---|---|---|---|
| 0 | 7% | 40% | 3 |
| 1 | 12% | 55% | 2 |
| 2 | 15% | 75% | 2 |
| 3 | 20% | 85% | 1 |

**Floor computation** (Phase 2):
```
tier_floor = high_water_roe × (tier.lock_hw_pct / 100)  → convert to price
hw_retrace_floor = high_water_price × (1 - retrace_threshold / 100 / leverage)
effective_floor = max(tier_floor, hw_retrace_floor)  # for LONG
```

### Breach Counting
- Each tick where `price <= floor_price` (LONG) increments breach count
- When `breach_count >= breaches_required` → position closed
- Breach count resets to 0 when price recovers above floor (and not advancing tier)
- On Phase 1→2 transition, breach count resets to 0

## Conviction Tiers

| Min Score | Absolute Floor | Hard Timeout | Weak Peak Cut | Dead Weight Cut |
|---|---|---|---|---|
| 6 (default) | -18% ROE | 25 min | 12 min | 8 min |
| 8 | -25% ROE | 45 min | 20 min | 15 min |
| 10 | -30% ROE | 60 min | 30 min | 20 min |

The `dsl.yaml` uses score≥6 as the default preset. Conviction tier support is not yet in the plugin runtime.

## Stagnation TP

| Parameter | Value |
|---|---|
| Enabled | Yes (MANDATORY) |
| Min ROE | 10% |
| HW Stale Minutes | 45 |

**Critical**: Mantis's config JSON notes: "MANDATORY. Fox has this. Mantis removed it and underperformed. Do not disable." Not yet supported by the plugin runtime.

## Scanner → DSL State Template

The scanner's `build_dsl_state_template()` creates the complete DSL state for each signal. The higher CONTRIB_ACCEL_THRESHOLD (0.003) filters Stalker entries **before** DSL state is created — only entries with genuine SM acceleration get templates.

## Plugin Migration Notes

**Maps directly**: Phase 1/2 retrace, breaches, tiers, time-based cuts, max_loss_pct.

**Not yet supported**: `stagnation_tp`, `conviction_tiers`, `lock_mode`, `phase2_trigger_roe`.

## MANTIS-Specific Notes

- **contrib_accel threshold 0.003**: MANTIS's unique experiment. Stalker entries need genuine SM acceleration to earn contribution points. Weak positive velocity is ignored entirely (no +1 tier).
- This means MANTIS produces fewer Stalker entries than ORCA — only the strongest accumulation patterns pass. However, the entries that do pass should have higher conviction and better DSL outcomes.
- The DSL config itself is unchanged — the quality improvement happens at the entry gate.
- MANTIS data showed that stagnation TP was critical: removing it caused underperformance. This is the skill that proved stagnation TP is mandatory.
