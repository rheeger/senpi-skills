# 🐅 TIGER v4.1 — Multi-Scanner Goal-Based Trading

The most complex hunter in the Senpi zoo. Five parallel scanners — compression, correlation, momentum, funding, and reversion — scanning 230 assets through a prescreener that narrows to the top 30. A meta-optimizer called ROAR tracks which scanners are producing winners and automatically throttles the underperformers. 17 scripts, 12 crons, the broadest signal coverage of any skill.

Give it a budget, a target, and a deadline. It adjusts aggression automatically.

## What TIGER Does

TIGER runs five specialized scanners simultaneously, each looking for a different pattern:

- **Compression** — Bollinger Band squeeze + OI breakout. Volatility compression resolving with new money.
- **Correlation** — BTC/ETH makes a move, find alts that haven't caught up yet.
- **Momentum** — Price move + volume spike. Trend confirmation with conviction.
- **Reversion** — RSI extremes + divergence. Overextended assets snapping back.
- **Funding** — Extreme funding rates. Enter against the crowd to collect the rate.

A prescreener runs every 5 minutes to score all 230+ Hyperliquid assets cheaply and produce a top-30 candidate list. The five scanners only analyze these candidates, saving API calls and focusing attention.

ROAR (the meta-optimizer) runs every 8 hours, analyzes which scanners are actually making money, and adjusts their aggression parameters. Scanners that are losing get throttled. Scanners that are winning get more room. TIGER is the only skill in the zoo that learns from its own results.

## What's in v4.1

**Bootstrap gate.** Agent checks `config/bootstrap-complete.json` every session. If missing, silently creates all 12 crons before responding.

**Notification silencing.** All crons run on isolated sessions. DSL moved from main to isolated. NO_REPLY for idle cycles. The agent only alerts on position OPENED, CLOSED, ROAR aggression change, risk halt, or critical error.

**Dead weight cut disabled.** No time-based exits that kill correct-direction trades early.

**All crons isolated.** Zero main session crons — prevents context bloat and session lock contention.

## Architecture

```
tiger-v4/
├── README.md                      ← You're here
├── tiger-strategy/                ← The skill
│   ├── SKILL.md                   ← Full logic for the agent
│   ├── tiger-config.json          ← Strategy configuration
│   ├── scripts/                   ← 17 Python scripts
│   │   ├── prescreener.py         ← Scores 230 assets → top 30
│   │   ├── compression-scanner.py ← BB squeeze + OI breakout
│   │   ├── momentum-scanner.py    ← Price move + volume spike
│   │   ├── reversion-scanner.py   ← RSI extreme + divergence
│   │   ├── correlation-scanner.py ← BTC/ETH → lagging alts
│   │   ├── funding-scanner.py     ← Extreme funding arb
│   │   ├── oi-tracker.py          ← OI history accumulator
│   │   ├── goal-engine.py         ← Adaptive aggression
│   │   ├── risk-guardian.py       ← Drawdown + daily loss
│   │   ├── tiger-exit.py          ← Smart exit logic
│   │   ├── dsl-v4.py              ← 10-tier trailing stops
│   │   ├── roar-analyst.py        ← Meta-optimizer
│   │   ├── tiger-setup.py         ← Strategy initialization
│   │   ├── create-dsl-state.py    ← DSL bootstrapper
│   │   ├── tiger_config.py        ← Shared config/MCP helpers
│   │   ├── tiger_lib.py           ← Technical analysis (pure stdlib)
│   │   └── roar_config.py         ← ROAR configuration
│   └── references/
│       ├── cron-templates.md
│       ├── config-schema.md
│       ├── scanner-details.md
│       ├── setup-guide.md
│       └── state-schema.md
└── workspace/
    ├── AGENTS.md                  ← Agent behavior + bootstrap gate
    ├── BOOTSTRAP.md               ← Startup sequence
    ├── HEARTBEAT.md               ← Periodic checks
    └── MEMORY.md                  ← Long-term memory (template)
```

## 12-Cron Architecture (all isolated)

| # | Cron | Interval | Purpose |
|---|---|---|---|
| 1 | Prescreener | 5 min | Score 230 assets → top 30 |
| 2 | Compression | 5 min | BB squeeze + OI breakout |
| 3 | Momentum | 5 min | Price + volume |
| 4 | Reversion | 5 min | RSI extreme + divergence |
| 5 | Correlation | 3 min | BTC/ETH → lagging alts |
| 6 | Funding | 30 min | Extreme funding rates |
| 7 | OI Tracker | 5 min | OI history accumulation |
| 8 | Goal Engine | 1 hr | Aggression recalculation |
| 9 | Risk Guardian | 5 min | Drawdown + daily loss |
| 10 | DSL Trailing Stop | 30 sec | 10-tier trailing stops |
| 11 | Exit Checker | 5 min | Time stops + stagnation |
| 12 | ROAR Analyst | 8 hr | Meta-optimizer |

All crons run on **isolated sessions** with `agentTurn` payloads. NO_REPLY for idle cycles.

## DSL Configuration: High Water Mode

TIGER targets **DSL High Water Mode** for trailing stops — percentage-of-peak locks that trail infinitely.

**Spec:** https://github.com/Senpi-ai/senpi-skills/blob/main/dsl-dynamic-stop-loss/dsl-high-water-spec%201.0.md

TIGER currently runs DSL v4 with 10 fixed tiers (5% → 100% ROE). High Water Mode upgrades this to percentage-of-peak locks where the stop is always a percentage of the highest ROE reached, with no ceiling. The tier design is pattern-specific:

| Pattern | Phase 1 Floor | Phase 2 Trigger | Notes |
|---|---|---|---|
| Compression | 1.5% notional | +7% ROE | Standard — breakout or bust |
| Correlation | 1.5% notional | +5% ROE | Tight — the lag window closes fast |
| Momentum | 1.2% notional | +7% ROE | Tighter — momentum reverses fast |
| Reversion | 1.5% notional | +8% ROE | Wider — expect 2-3 ATR before the snap |
| Funding | 2.0% notional | +10% ROE | Widest — income-based, needs room |

**Current workaround** (until DSL engine supports `lockMode: "pct_of_high_water"`): use the existing 10-tier fixed `lockPct` configuration. After engine update, switch each pattern's DSL profile to High Water tiers with `lockHwPct`. The pattern-specific Phase 1 floors and retrace settings stay the same — only the Phase 2 lock calculation changes.

**Legacy fallback tiers (use today):**
```json
{
  "tiers": [
    {"triggerPct": 5,  "lockPct": 2},
    {"triggerPct": 10, "lockPct": 6},
    {"triggerPct": 15, "lockPct": 11},
    {"triggerPct": 20, "lockPct": 16, "retrace": 0.012},
    {"triggerPct": 30, "lockPct": 25, "retrace": 0.010},
    {"triggerPct": 40, "lockPct": 34, "retrace": 0.008},
    {"triggerPct": 50, "lockPct": 44, "retrace": 0.006},
    {"triggerPct": 65, "lockPct": 57, "retrace": 0.005},
    {"triggerPct": 80, "lockPct": 72, "retrace": 0.004},
    {"triggerPct": 100, "lockPct": 90, "retrace": 0.003}
  ]
}
```

**High Water tiers (after engine update):**
```json
{
  "lockMode": "pct_of_high_water",
  "tiers": [
    {"triggerPct": 7,  "lockHwPct": 35, "consecutiveBreachesRequired": 3},
    {"triggerPct": 12, "lockHwPct": 50, "consecutiveBreachesRequired": 2},
    {"triggerPct": 20, "lockHwPct": 70, "consecutiveBreachesRequired": 2},
    {"triggerPct": 30, "lockHwPct": 85, "consecutiveBreachesRequired": 1}
  ]
}
```

## Optional: Trading Strategy Variant

TIGER is a full skill with broad signal coverage. For users who want a focused configuration:

| Strategy | What Changes |
|---|---|
| **TIGER Sniper** | Compression + correlation scanners only. Other 3 disabled. Highest confluence bar, fewest trades. |

Start with vanilla TIGER. The five-scanner approach provides the broadest coverage. TIGER Sniper is for users who want to concentrate on the two highest-performing patterns.

## Risk Management

| Rule | Limit | Default |
|---|---|---|
| Max single trade loss | 3% of balance | 3 |
| Max daily loss | 8% of day-start balance | 8 |
| Max drawdown from peak | 15% | 15 |
| Max concurrent positions | 2 | 2 |
| OI collapse exit | OI drops > 25% in 1h | Auto |
| Funding reversal exit | Funding flips on FUNDING_ARB | Auto |
| Stagnation TP | ROE ≥ 8%, HW stale 1h | Auto |

## ROAR Meta-Optimizer

ROAR runs every 8 hours and analyzes trade results by scanner type. It calculates:
- Win rate per scanner
- Average P&L per scanner
- Fee drag per scanner

If a scanner is consistently losing, ROAR tightens its entry threshold. If a scanner is winning, ROAR gives it more room. This is automated — the agent doesn't need to intervene.

TIGER is the only skill in the zoo with a built-in learning system. When SAITA ships the `senpi-learner` plugin, every skill will get this capability.

## Quick Start

1. Deploy to OpenClaw with Senpi MCP configured
2. Copy `workspace/` files to `/data/workspace/`
3. Copy `tiger-strategy/` to `/data/workspace/skills/tiger-strategy/`
4. Edit `tiger-config.json` — set strategy_id, wallet, budget, target, deadline
5. Agent reads AGENTS.md → runs bootstrap → creates all 12 crons
6. The TIGER hunts

## Requirements

- [OpenClaw](https://openclaw.ai) agent with cron support
- [Senpi](https://senpi.ai) MCP access token
- [mcporter](https://github.com/nichochar/mcporter-cli) CLI
- Python 3.8+ (no external dependencies)

## License

Apache-2.0 — Built by Senpi (https://senpi.ai). Attribution required for derivative works.
Source: https://github.com/Senpi-ai/senpi-skills
