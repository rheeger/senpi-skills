# 🛡️ SENTINEL v1.0 — Quality Trader Convergence Scanner

Part of the [Senpi Trading Skills Zoo](https://github.com/Senpi-ai/senpi-skills).

## What SENTINEL Does

Finds assets where SM interest is accelerating, then verifies that the traders behind the move are proven performers. Three layers: rising contribution velocity → quality trader confirmation via momentum events → optional top trader cross-check.

The inverted pipeline catches the trade BEFORE top traders hit the leaderboard. By the time they're in the top 20, SENTINEL has already entered.

## Directory Structure

```
sentinel-v1.0/
├── README.md
├── SKILL.md
├── config/
│   └── sentinel-config.json
└── scripts/
    ├── sentinel-scanner.py
    └── sentinel_config.py
```

## Quick Start

1. Deploy config and scripts to your Senpi agent
2. Create scanner cron (3 min, main) and DSL cron (3 min, isolated)
3. Fund with $1,000

## Requires

- dsl-v5.py with Patch 1 + Patch 2
- Senpi MCP: `leaderboard_get_markets`, `leaderboard_get_momentum_events`, `leaderboard_get_top`

## License

MIT — Built by Senpi (https://senpi.ai).

## Changelog

### v1.0
- Inverted pipeline: asset discovery → quality trader verification → entry
- Three-layer scoring: SM velocity + TCS/TRP quality traders + top trader cross-check
- Tier 1 + Tier 2 momentum events scanned for asset-specific quality confirmations
- DSL v1.1.1: `highWaterPrice: null`, correct field names, dynamic `absoluteFloorRoe`
