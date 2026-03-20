# 🐆 JAGUAR v1.0 — Three-Mode Scanner + Gen-2 Intelligence + Pyramiding

Part of the [Senpi Trading Skills](https://github.com/Senpi-ai/senpi-skills).

## What JAGUAR Does

JAGUAR is a three-mode emerging movers scanner with gen-2 signal intelligence and position pyramiding. Every lesson from 30 live agents and $26K capital is hardcoded in the scanner.

### Three Entry Modes
- **STALKER** (Score >= 6): SM accumulating over 3+ scans, contribution building, 4H aligned
- **STRIKER** (Score >= 9): Violent FIRST_JUMP, 10+ rank jump from deep, volume confirmed
- **HUNTER** (Score >= 8): Independent gen-2 signal — Tier 2 momentum events + quality traders + velocity divergence

### Gen-2 Confirmation Layer
All signals scored with TCS/TRP quality tags from Tier 2 momentum events ($5.5M+ threshold). ELITE/RELIABLE traders boost signals. CHOPPY+CONSERVATIVE hard-blocked. Contribution velocity divergence adds scoring.

### Pyramiding
Adds 50% margin to winning Phase 2 positions (ROE > 7%) when the thesis is re-confirmed — asset still climbing SM leaderboard OR fresh momentum event. Max 1 per position, account margin capped at 60%.

## Hardcoded in the Scanner

- XYZ equities filtered at scan parse level
- Leverage 7-10x in constraints block
- Max 7 positions (pyramids don't count)
- DSL state template per-signal with correct breaches, dead weight, conviction scaling
- Stagnation TP, daily loss limit, asset cooldown all in output
- TCS/TRP quality scoring and hard blocks
- Agent cannot override — signals that violate gates don't appear in output

## Quick Start

1. Deploy to `/data/workspace/skills/jaguar-strategy/`
2. Deploy `config/jaguar-config.json`, `scripts/jaguar-scanner.py`, `scripts/jaguar_config.py`
3. Create scanner cron (90s, main) and DSL cron (3 min, isolated)
4. Fund with $1,000

## API Calls Per Scan

| Call | Purpose |
|---|---|
| `leaderboard_get_markets` (limit=100) | SM concentration (all modes) |
| `leaderboard_get_momentum_events` | Tier 2 events + TCS/TRP tags |
| `market_get_asset_data` per candidate | Volume confirmation (signals that pass gates only) |
| `strategy_get_clearinghouse_state` | Position count + pyramid ROE check |

Base: 3 calls/scan + N volume checks for candidates.

## License

MIT — see root repo LICENSE.
