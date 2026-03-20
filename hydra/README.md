# 🐉 HYDRA v1.0 — Multi-Source Squeeze Scanner

Part of the [Senpi Trading Skills](https://github.com/Senpi-ai/senpi-skills).

## What HYDRA Does

HYDRA detects crowded positions across crypto perpetuals using 6 independent signal sources, enters trades with conviction-based sizing, and manages them with DSL v1.1.1 trailing stops. Includes an independent monitor watchdog for account health and signal reversal detection.

## Signal Sources

| # | Source | Weight | Role |
|---|--------|--------|------|
| 1 | FDD — Funding Divergence | 0-30 | Primary gate |
| 2 | LCD — Liquidation Cascade | 0-25 | Liquidation clusters |
| 3 | OIS — Open Interest Surge | 0-20 | Leverage flow |
| 4 | MED — Momentum Exhaustion | -10 to +5 | Confirmation/penalty |
| 5 | EM — Emerging Movers | -8 to +15 | SM consensus |
| 6 | OPP — Opportunity Scanner | -999 to +10 | Trend alignment gate |

## Three Crons

```
python3 /data/workspace/skills/hydra/scripts/hydra-scanner.py     # 5 min, main
python3 /data/workspace/skills/dsl-dynamic-stop-loss/scripts/dsl-v5.py --state-dir /data/workspace/skills/hydra/state  # 3 min, isolated
python3 /data/workspace/skills/hydra/scripts/hydra-monitor.py     # 5 min, isolated
```

## v1.0.1 Fixes

- MCP calls use mcporter CLI subprocess (was REST API — wouldn't work on agents)
- Clearinghouse parsing unwraps main/xyz nesting correctly (positions were invisible)
- Asset data fetched once per candidate, passed to all 6 sources (was 5 redundant calls)
- Leaderboard data cached across discover_candidates, market_regime, source_em, and sizing
- SKILL.md hardened with 8 critical agent rules
- Stale placeholder directory removed

## License

MIT — Copyright 2026 Senpi (https://senpi.ai)
