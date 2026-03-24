# ORCA v1.2 — DSL Implementation

## Overview

ORCA v1.2 is a **dual-mode** emerging movers scanner with two entry modes:
- **STALKER**: SM accumulating over 3+ scans, score 7+. Enters before the crowd.
- **STRIKER**: Violent first-jump + volume ≥ 1.5x, score 9+. Enters the explosion.

The DSL (Dynamic Stop Loss) is the exit engine. It protects capital in Phase 1 and locks profit in Phase 2 using a high-water trailing floor with tiered progression.

## DSL Two-Phase Model

### Phase 1 — Capital Protection
Active from position open until ROE reaches the first tier trigger (7%).

**Goal**: Limit downside while giving the trade room to work.

| Parameter | Value | Source |
|---|---|---|
| Retrace threshold | 3% ROE | `retraceThreshold: 0.03` |
| Consecutive breaches required | 3 | Fox's #1 bug fix — was 1, caused single-wick kills |
| Absolute floor | -18% ROE (score≥6) | `absoluteFloorRoe: -18` |

**Time-based cuts** (conviction-scaled, score≥6 defaults):

| Cut | Interval | Behavior |
|---|---|---|
| Hard timeout | 25 min | Close regardless of P&L |
| Weak peak cut | 12 min | Close if peak ROE < 3% and current < peak (bumped +0.5% then stalled) |
| Dead weight cut | 8 min | Close if position never went positive |

**Floor computation** (Phase 1):
```
trailing_floor = high_water_price × (1 - retrace_threshold / 100 / leverage)
absolute_floor = entry_price × (1 - |absoluteFloorRoe| / 100 / leverage)
effective_floor = max(trailing_floor, absolute_floor)  # for LONG
```

### Phase 2 — Profit Protection
Activated when ROE hits the first tier trigger (7% → `phase2_trigger_tier: 0`).

**Goal**: Lock increasing % of profit as the trade runs higher.

| Parameter | Value |
|---|---|
| Retrace threshold | 1.5% ROE |
| Consecutive breaches required | 2 |

**Tier progression** (lock_hw_pct of high-water ROE):

| Tier | Trigger ROE | Lock HW % | Breaches Required |
|---|---|---|---|
| 0 | 7% | 40% | 3 |
| 1 | 12% | 55% | 2 |
| 2 | 15% | 75% | 2 |
| 3 | 20% | 85% | 1 |

**Example**: At 15% ROE high-water, Tier 2 locks 75% → floor at 11.25% ROE.

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

The scanner selects Phase 1 parameters based on entry signal score. Higher-conviction entries get more room:

| Min Score | Absolute Floor | Hard Timeout | Weak Peak Cut | Dead Weight Cut |
|---|---|---|---|---|
| 6 (default) | -18% ROE | 25 min | 12 min | 8 min |
| 8 | -25% ROE | 45 min | 20 min | 15 min |
| 10 | -30% ROE | 60 min | 30 min | 20 min |

**Score 6** is the tightest (fastest cuts, smallest loss tolerance). **Score 10** gives maximum room for high-conviction signals.

The `dsl.yaml` uses score≥6 as the default preset. Conviction tier support is not yet in the plugin runtime.

## Stagnation TP

| Parameter | Value |
|---|---|
| Enabled | Yes (MANDATORY) |
| Min ROE | 10% |
| HW Stale Minutes | 45 |

If position is ≥10% ROE but high-water hasn't moved in 45 minutes → take profit. This catches trades that run up then flatline — the move is over.

**Note**: Fox has this. Mantis removed it and underperformed. Do not disable.

Not yet supported by the plugin runtime.

## Scanner → DSL State Template

The scanner's `build_dsl_state_template()` (lines 494-552) creates the complete DSL state for each signal:

1. Signal detected with score → conviction tier selected
2. Phase 1 params set from conviction tier (timeouts, floor)
3. Phase 2 params + tiers hardcoded from `DSL_TIERS`
4. State written directly — no merging with `dsl-profile.json`

This eliminates every DSL bug found in the Fox audit (wrong floor values, missing dead weight, breaches=1).

## Plugin Migration Notes

**Maps directly**:
- Phase 1/2 retrace thresholds, breaches
- Tier progression (trigger_pct, lock_hw_pct, breaches)
- Phase 1 time-based cuts (hard_timeout, weak_peak_cut, dead_weight_cut)
- max_loss_pct (absolute floor)

**Not yet supported**:
- `stagnation_tp` — needs plugin implementation
- `conviction_tiers` — score-based Phase 1 scaling
- `lock_mode` — only pct_of_high_water exists (hardcoded)
- `phase2_trigger_roe` — plugin uses tier index (`phase2_trigger_tier: 0`)

## ORCA-Specific Notes

- Baseline dual-mode scanner — no experimental tweaks to scoring
- Standard contrib velocity threshold (0.001) for CONTRIB_ACCEL
- Both Stalker and Striker signals get DSL templates
- v1.2 fixes from Fox's live data: minScore 6→7, minTotalClimb 5→8, 3-loss streak gate
- Stalker signals at score 7 use tightest DSL (8 min dead weight)
- Striker signals at score 9+ use wider DSL (15-20 min dead weight)
