# 🦡 WOLVERINE v2.0 — HYPE Alpha Hunter

Part of the [Senpi Trading Skills](https://github.com/Senpi-ai/senpi-skills).

## What Changed

v1.1 lost -22.7% because the scanner's "thesis exit" killed 25 of 27 trades before DSL could manage them. On HYPE (which wicks 5-10% ROE routinely), the scanner saw every normal wick as thesis invalidation and chopped winners that would have run to +30%.

v2.0 removes the thesis exit entirely. Scanner decides entries. DSL manages all exits. Once a position is open, the scanner explicitly refuses to re-evaluate it.

## Key Settings

| Setting | Value |
|---|---|
| Asset | HYPE only |
| Leverage | 7x (down from 10x) |
| Entry score | 8+ (up from ~5) |
| 4H/1H alignment | Required |
| Max entries/day | 4 |
| Cooldown | 3 hours |
| Phase 1 floor | -20% ROE |
| Phase 2 trigger | +15% ROE |
| Thesis exit | **REMOVED** |

## The Proof

v1.1 Trade #6: HYPE LONG, +29.92% ROE, held 757 minutes. The one trade where the scanner accidentally let it run was worth more than all other 13 winners combined.

## License

MIT — Copyright 2026 Senpi (https://senpi.ai)
