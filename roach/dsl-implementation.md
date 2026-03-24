# ROACH v1.0 — DSL Implementation

## Overview

ROACH v1.0 is a **Striker-only** scanner. Stalker is disabled entirely.

- **STRIKER**: Violent first-jump + volume ≥ 1.5x, score 9+, min 4 reasons. Enter the explosion.
- **STALKER**: Disabled. Code still runs (for scan history building) but signals are never emitted.

**ROACH's hypothesis**: Stalker is pure drag. Fox data showed 17 Stalker trades at score 6-7 with 17.6% win rate and -$91.32 net. The one Striker signal (ZEC LONG score 11) was the only explosive profile worth trading. ROACH tests whether removing Stalker entirely improves outcomes.

Cockroaches survive anything. ROACH survives by not trading when there's no explosion. Long stretches of silence — that patience IS the edge.

The DSL exit engine is identical to ORCA, FOX, and MANTIS.

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

The `dsl.yaml` uses score≥6 as the default preset. However, **ROACH's entries are always score 9+** (Striker minScore), so in practice Python selects the score≥8 tier (45min hard timeout, 20min weak peak, 15min dead weight, -25% floor). When conviction tiers are supported in the plugin, ROACH would benefit from using the wider timeouts.

## Stagnation TP

| Parameter | Value |
|---|---|
| Enabled | Yes (MANDATORY) |
| Min ROE | 10% |
| HW Stale Minutes | 45 |

Not yet supported by the plugin runtime.

## Scanner → DSL State Template

The scanner's `build_dsl_state_template()` creates DSL state only for Striker signals. The `run()` function (line 575-596) skips Stalker detection entirely — `stalkerSignals` is always `[]` in output.

## Plugin Migration Notes

**Maps directly**: Phase 1/2 retrace, breaches, tiers, time-based cuts, max_loss_pct.

**Not yet supported**: `stagnation_tp`, `conviction_tiers`, `lock_mode`, `phase2_trigger_roe`.

## ROACH-Specific Notes

- **Striker-only**: The most extreme filter. No Stalker trades, period. Striker signals are rare (1-3/day in active markets, 0 in chop).
- **Higher effective conviction**: Since all entries are score 9+, Python selects wider Phase 1 timeouts. The default `dsl.yaml` preset uses score≥6 (tightest), which is more conservative than what ROACH uses in Python. This is intentional — the tighter preset is safer.
- **No stalker streak gate**: ROACH doesn't need the consecutive-loss streak gate since it never takes Stalker trades.
- **Output always includes** `stalkerDisabled: true` and `stalkerSignals: []`.
- **Trade frequency**: Very low. The patience is the strategy — only enter on violent volume-confirmed explosions.
