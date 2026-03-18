# BALD EAGLE v1.0

**XYZ Equities Scanner for Hyperliquid**

The first Senpi skill built exclusively for tokenized US equities/commodities on Hyperliquid's xyz dex. Every other skill in the zoo bans XYZ. BALD EAGLE only trades it.

## Why

XYZ was net negative across 26 agents — so we banned it from every scanner. But Mantis's xyz:SKHX hit +91.71% ROE, and 3 of the top 10 leaderboard traders on March 17 held xyz:SILVER. The problem wasn't XYZ — it was applying crypto scanners to equities.

BALD EAGLE is purpose-built for how XYZ actually behaves: fewer SM traders (20-40 vs 100-400), lower leverage caps (10-25x), session-driven volatility, macro correlation (SILVER/GOLD move together, not with BTC), and crowded directional funding.

## Quick Start

Scanner cron (systemEvent):
```
python3 /data/workspace/skills/bald-eagle/scripts/bald-eagle-scanner.py
```

DSL cron (agentTurn):
```
python3 /data/workspace/skills/dsl-dynamic-stop-loss/scripts/dsl-v5.py --state-dir /data/workspace/skills/bald-eagle/state
```

## Directory Structure

```
bald-eagle-v1.0/
├── README.md                    # This file
├── SKILL.md                     # Full spec — the agent reads this
├── config/
│   └── skill-config.json        # All configurable parameters
└── scripts/
    ├── bald-eagle-scanner.py    # Scanner logic
    └── bald_eagle_config.py     # Standalone config helper
```

## Comparison

| Dimension | BALD EAGLE | ORCA | POLAR | RAPTOR |
|-----------|------------|------|-------|--------|
| Assets | xyz: only | Crypto perps | ETH only | Crypto perps |
| Primary Signal | leaderboard_get_markets (dex=xyz) | SM rank climbing | SM leaderboard | Tier 2 momentum events |
| Min Traders | 10 | 30 | N/A | N/A |
| Max Leverage | Asset-capped (10-25x) | 7x | 7x | 7x |
| Trade Freq | 1-3/day | 3-5/day | 1-2/day | 3-5/day |
| XYZ Filter | ONLY xyz: | BAN xyz: | BAN xyz: | BAN xyz: |

## License

MIT — Copyright 2026 Senpi (https://senpi.ai)
Source: https://github.com/Senpi-ai/senpi-skills
