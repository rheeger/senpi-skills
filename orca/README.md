# 🐋 ORCA v1.1.1 — Hardened Dual-Mode Scanner

Part of the [Senpi Trading Skills](https://github.com/Senpi-ai/senpi-skills).

## What ORCA Does

ORCA is the definitive version of the Vixen/Fox dual-mode emerging movers scanner. Every lesson from 5+ days of live trading across 22 agents is hardcoded into the scanner itself.

v1.1 adds the DSL state template directly in scanner output — the agent writes it as the state file, bypassing dsl-profile.json and wolf_config.py builders that broke every other agent's DSL config.

## v1.1 Changes (DSL Audit)

| Bug Found | Agents Affected | Fix in v1.1 |
|---|---|---|
| Phase 1 breaches = 1 (single wick kills) | Fox, Grizzly | Hardcoded to 3 in dslState |
| Dead weight = 0 (losers bleed for hours) | Fox, Vixen, Mantis, Jackal | Set per-score (10/15/20) in dslState |
| stagnationTp stripped by builder | Jackal, Dire Wolf | Included in dslState, bypasses builder |
| dsl-v5.py reads top-level, not per-tier | All Wolf-based agents | Top-level values set correctly per-score |

## Hardcoded in the Scanner

- XYZ equities filtered at scan parse level
- Leverage 7-10x in constraints block
- DSL state template per-signal with correct breaches, dead weight, conviction scaling
- Stagnation TP, daily loss limit, asset cooldown all in output
- Agent cannot override — signals that violate gates don't appear in output

## Quick Start

1. Deploy `config/orca-config.json` to your Senpi agent
2. Deploy `scripts/orca-scanner.py` and `scripts/orca_config.py`
3. Create scanner cron (90s, main) and DSL cron (3 min, isolated)
4. Fund with $1,000

## License

MIT — see root repo LICENSE.

## Changelog

### v1.1.1
- Fixed DSL field names: `phase1MaxMinutes` (was `hardTimeoutMinutes`), `deadWeightCutMin` (was `deadWeightCutMinutes`)
- `highWaterPrice` initialized as `null` (was `0`) — lets dsl-v5.py set from actual entry price on first tick
- Removed static `absoluteFloor` price values — dsl-v5.py now calculates dynamically from `absoluteFloorRoe`
- Requires dsl-v5.py with Patch 1 (dynamic absoluteFloorRoe calculator) and Patch 2 (highWaterPrice null handling)
