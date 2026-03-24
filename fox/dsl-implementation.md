# FOX v2.0 — DSL Implementation

## Overview

FOX v2.0 is a **dual-mode** emerging movers scanner with one experimental tweak:
- **STALKER**: SM accumulating over 3+ scans, score 7+, **minReasons=3**. Requires breadth of confirmation.
- **STRIKER**: Violent first-jump + volume ≥ 1.5x, score 9+. Enter the explosion.

**FOX's experiment**: Stalker entries must have at least 3 distinct scoring reasons (not just pass the score threshold). Fox v1.0 data showed weakest losers had only 2 reasons — `STALKER_CLIMB + SM_ACTIVE` — reaching score 7 via base award + trader count + time bonus without real breadth. Requiring 3 reasons forces at least one additional signal (contribution acceleration, deep start, etc.).

The DSL exit engine is identical to ORCA, MANTIS, and ROACH.

## DSL Two-Phase Model

### Phase 1 — Capital Protection
Active from position open until ROE reaches the first tier trigger (7%).

| Parameter | Value | Source |
|---|---|---|
| Retrace threshold | 3% ROE | `retraceThreshold: 0.03` |
| Consecutive breaches required | 3 | Fox's #1 bug fix — was 1, caused single-wick kills |
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

Fox has this enabled. Mantis removed it and underperformed. Not yet supported by the plugin runtime.

## Scanner → DSL State Template

The scanner's `build_dsl_state_template()` creates the complete DSL state for each signal. The minReasons=3 gate filters Stalker entries **before** DSL state is created — only entries with sufficient breadth get a DSL template.

## Plugin Migration Notes

**Maps directly**: Phase 1/2 retrace, breaches, tiers, time-based cuts, max_loss_pct.

**Not yet supported**: `stagnation_tp`, `conviction_tiers`, `lock_mode`, `phase2_trigger_roe`.

## FOX-Specific Notes

- **minReasons=3**: FOX's unique experiment. Stalker entries need at least 3 distinct reasons. This filters thin signals that would enter and immediately bleed in Phase 1.
- In practice, the minReasons gate means FOX's Stalker trades tend to have higher quality — they've passed both score and breadth thresholds. This doesn't change DSL config but means DSL sees fewer "weak peak bleed" entries.
- Fox v1.0 data: 17 Stalker trades at score 6-7 with 17.6% win rate (-$91.32). The minReasons gate would have filtered most of these.
- DSL bug history: Fox was the first skill to expose breaches=1 and deadWeightCut=0 bugs, which led to the hardcoded fixes in all scanners.
