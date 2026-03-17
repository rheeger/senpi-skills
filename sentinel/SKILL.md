---
name: sentinel-strategy
description: >-
  SENTINEL v1.0 — Quality Trader Convergence Scanner. Inverted pipeline: finds
  assets where SM is accelerating FIRST, then checks who's profiting from them
  using momentum event TCS/TRP quality tags. Catches the trade BEFORE top traders
  hit the leaderboard, not after. Three confirmation layers: rising SM contribution
  velocity + quality traders confirmed via momentum events + optional top trader
  cross-check. 2-4 trades per day, highest conviction in the zoo.
license: MIT
metadata:
  author: jason-goldberg
  version: "1.0"
  platform: senpi
  exchange: hyperliquid
---

# 🛡️ SENTINEL v1.0 — Quality Trader Convergence Scanner

Catch the move BEFORE the top traders hit the leaderboard.

## The Inverted Pipeline

Most scanners: "find interesting assets → enter." SENTINEL: "find rising assets → check if quality traders are behind them → enter only when proven performers confirm the move."

The difference matters. By the time 3+ traders appear in the top 20 on the same asset, the move is mature. SENTINEL catches the window between "SM starts accumulating in an asset" and "the traders driving it reach the top of the leaderboard."

```
Every 3 minutes:

LAYER 1 — Where is SM accelerating?
  └─ leaderboard_get_markets
  └─ Filter: contribution_pct_change_4h >= 3% (SM building)
  └─ Filter: rank 6-40 (not peaked, not invisible)
  └─ Filter: 25+ traders, 4H aligned, leverage >= 5x
  └─ Sort by contribution velocity → top 5 candidates

LAYER 2 — WHO is profiting from these assets?
  └─ leaderboard_get_momentum_events (Tier 1 + Tier 2)
  └─ For each candidate: find events where asset matches
  └─ Filter by trader quality: TCS ELITE/RELIABLE + TRP SNIPER/AGGRESSIVE/BALANCED
  └─ Filter: concentration >= 0.4 + direction matches SM
  └─ Need 2+ quality traders confirmed

LAYER 3 — Are top traders already in? (bonus, not required)
  └─ leaderboard_get_top (top 30)
  └─ Cross-check: does this asset appear in any top trader's top_markets?
  └─ If yes: bonus points (confirms the move has legs)
  └─ If no: still valid (we're early — that's the point)
```

## Why Inverted Works Better

| Approach | Pipeline | Problem |
|---|---|---|
| Watch top traders | Find hot traders → see what they trade | By then the move is mature |
| Watch assets | Find rising assets → enter | No quality filter on who's behind it |
| **SENTINEL** | **Find rising assets → verify quality traders → enter** | **Catches the move early with quality confirmation** |

The key insight: `leaderboard_get_markets` with `contribution_pct_change_4h` finds assets where SM is building RIGHT NOW. Momentum events tell us WHO is profiting — and TCS/TRP tell us if those traders are any good. The asset discovery is fast (one call). The quality check is targeted (only check events for the top 5 rising assets).

## Scoring (0-20 range)

### Layer 1: SM Velocity
| Signal | Points |
|---|---|
| Surging SM (>20% 4h contrib change) | 3 |
| Fast SM (>10%) | 2 |
| Rising SM (>3%) | 1 |
| Strong rank (top 15) | 2 |
| Mid rank (15-25) | 1 |
| Deep SM (100+ traders) | 1 |
| Price lag (<2% move) | 1 |

### Layer 2: Quality Traders (the differentiator)
| Signal | Points |
|---|---|
| Elite convergence (4+ quality traders) | 5 |
| Strong convergence (3 quality traders) | 4 |
| Convergence (2 quality traders) | 3 |
| Double Tier 2 events | 2 |
| Single Tier 2 event | 1 |
| High conviction (avg concentration >70%) | 1 |

### Layer 3: Top Trader Bonus
| Signal | Points |
|---|---|
| 2+ top traders already in asset | 2 |
| 1 top trader present | 1 |

Minimum score: 8.

## Files

| File | Purpose |
|---|---|
| `scripts/sentinel-scanner.py` | Three-layer convergence scanner |
| `scripts/sentinel_config.py` | Standalone config helper |
| `config/sentinel-config.json` | Parameters |

## License

MIT — Built by Senpi (https://senpi.ai).
