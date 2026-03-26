[senpi-skills-README (1).md](https://github.com/user-attachments/files/26288945/senpi-skills-README.1.md)
# Senpi Skills — Autonomous AI Trading Agents for Hyperliquid

30+ AI trading skills. Open source. Real money. Live tracked.

Senpi Skills is the open-source repository for autonomous trading strategies on [Hyperliquid](https://hyperliquid.xyz) via [Senpi](https://senpi.ai). Each skill is a self-contained trading agent that scans markets, enters and exits positions, manages trailing stops, and protects capital — autonomously, 24/7, with no human in the loop.

**Live tracker:** [strategies.senpi.ai](https://strategies.senpi.ai)
**Arena competition:** [senpi.ai/arena](https://senpi.ai/arena)

---

## Active Skills

### Top Performers

| Skill | Version | ROE | Description |
|---|---|---|---|
| 🐻‍❄️ [POLAR](./polar) | v1.0 | **+23.6%** | ETH lifecycle hunter. HUNT → RIDE → STALK → RELOAD. The proof that single-asset patience wins. |
| 🦗 [MANTIS](./mantis) | v3.0 | **+5.6%** | Hardened SM scanner. Contribution acceleration quality gate. Steady performer. |
| 🪳 [ROACH](./roach) | v1.0 | **+5.3%** | Striker-only. No Stalker. The A/B experiment winner — violent explosions only. |

### The Stalker vs Striker Experiment

Does Stalker (accumulation detection) add value on top of Striker (explosion detection)?

| Skill | Version | Strategy | ROE | Verdict |
|---|---|---|---|---|
| 🪳 [ROACH](./roach) | v1.0 | Striker only | +5.3% | **Leading** |
| 🐋 [ORCA](./orca) | v1.3 | Stalker + Striker | 0.0% | Just deployed — collecting data |
| 🪳 [ROACH-B](./roach) | v1.0 | Striker only (variant B) | -0.3% | Early — 4 trades |

### v2.0 Fleet (Hardened Rebuilds)

These agents replace v1.0 versions that failed due to infrastructure bugs (missing DSL wallet fields, thesis exit chopping winners, broken cron coordination). All v2.0 agents share: DSL state with wallet + size fields, no thesis exit, reduced leverage, daily entry caps.

| Skill | Version | Description | Replaces |
|---|---|---|---|
| 🦡 [WOLVERINE](./wolverine) | v2.0 | HYPE hunter. Entry-only scanner, 7x leverage, score 8+, 4H/1H alignment required. | v1.1 (-23.4%) |
| 🦅 [CONDOR](./condor) | v2.0 | Multi-asset (BTC/ETH/SOL/HYPE). Thesis exit removed. DSL manages exits. | v1.0.1 (-24.9%) |
| 🐆 [JAGUAR](./jaguar) | v2.0 | Striker-only. Stalker and Hunter removed. Pyramiding removed. | v1.0 (-29.3%) |
| 🦈 [SHARK](./shark) | v2.0 | SM conviction scanner. 8-cron pipeline consolidated to 1 scanner. 4-gate entry. | v1.0 (-4.6%) |

### New Strategies

| Skill | Version | Description |
|---|---|---|
| 🍋 [LEMON](./lemon) | v1.0 | **The Degen Fader.** Finds DEGEN/CHOPPY traders via `discovery_get_top_traders`, waits until they're bleeding at 10x+ leverage and -10%+ ROE, counter-trades them. Rides the liquidation cascade. |
| 🦅 [BALD EAGLE](./bald-eagle) | v2.0 | **XYZ Alpha Hunter.** Trades all 54 XYZ assets (commodities, indices, equities, currencies). Spread gate (>0.1% = rejected) filters illiquid assets. The only agent covering non-crypto markets. |

### Single-Asset Hunters

| Skill | Version | Asset | ROE | Description |
|---|---|---|---|---|
| 🐻‍❄️ [POLAR](./polar) | v1.0 | ETH | +23.6% | Three-mode lifecycle. The patience benchmark. |
| 🐻 [GRIZZLY](./grizzly) | v2.1.1 | BTC | +0.1% | BTC lifecycle hunter. Recovering. |
| 🐻 [KODIAK](./kodiak) | v2.0 | SOL | -2.3% | SOL hunter. Has $80 unrealized gains running. |
| 🦡 [WOLVERINE](./wolverine) | v2.0 | HYPE | 0.0% | Waiting for HYPE trend alignment. Correct behavior in chop. |
| 🐆 CHEETAH | v1.0 | HYPE | 0.0% | Different scanner than Wolverine. Zero trades in chop = correct. |

### Gen-2 Intelligence

| Skill | Version | Description |
|---|---|---|
| 🐉 [HYDRA](./hydra) | v1.0 | Six-source squeeze scanner. FDD primary gate. Recovering from threshold bug. |
| 🦅 [RAPTOR](./raptor) | v1.0 | Tier 2 momentum events + TCS/TRP quality tags. Waiting for signals. |
| 🔥 [PHOENIX](./phoenix) | v1.0.1 | Contribution velocity scanner. SM profit velocity diverging from price. |
| 🛡️ [SENTINEL](./sentinel) | v1.0 | Inverted pipeline: rising assets → verify quality traders. Most selective scanner. |

### Specialized Scanners

| Skill | Version | Description |
|---|---|---|
| 🦬 [BISON](./bison) | v1.2.1 | Conviction trend holder. Requires 4H/1H agreement. Zero trades in chop = correct. |
| 🐟 [BARRACUDA](./barracuda) | v1.0.1 | Funding decay collector. Building local funding history (230 assets, 11K+ snapshots). |
| 🦉 [OWL](./owl) | v5.2 | Contrarian crowding-unwind. |
| 🦅 [HAWK](./hawk-trading-bot) | v1.2 | Single best signal picker. 20x leverage (flagged — too high). |

### Volume Engine

| Skill | Version | Description |
|---|---|---|
| 🦈 [MAKO](./mako-strategy) | v5.1 | Self-contained volume generation engine. Single Python process, infinite loop, no crons, no LLM in execution path. Generates $200K+/day volume on BTC/ETH. |

### Shared Infrastructure

| Plugin | Purpose |
|---|---|
| [DSL Dynamic Stop Loss](./dsl-dynamic-stop-loss) | Trailing stop engine. [High Water Mode spec](./dsl-dynamic-stop-loss/dsl-high-water-spec%201.0.md). Being migrated to plugin runtime. |
| [Fee Optimizer](./fee-optimizer) | ALO vs MARKET decision, fee computations. |
| [Emerging Movers](./emerging-movers) | Leaderboard scanner shared by FOX, WOLF, and VIXEN. |
| [Opportunity Scanner](./opportunity-scanner) | Deep 4-stage funnel scanner. |
| [Senpi Onboard](./senpi-onboard) | Agent onboarding and account setup. |
| [Getting Started Guide](./senpi-getting-started-guide) | Interactive first-trade tutorial. |

---

## Retired Skills

Code preserved for reference. Each was retired based on live performance data or replaced by a v2.0 rebuild.

| Skill | Last Version | ROE | Replaced By |
|---|---|---|---|
| 🐋 [ORCA](./orca) | v1.1 | -10.0% | Orca v1.3 |
| 🐋 [ORCA](./orca) | v1.2 | -1.5% | Orca v1.3 (infrastructure failures) |
| 🦊 [FOX](./fox) | v2.0 | -9.3% | Experiment concluded — Roach won |
| 🦡 [WOLVERINE](./wolverine) | v1.1 | -23.4% | Wolverine v2.0 |
| 🦅 [CONDOR](./condor) | v1.0.1 | -24.9% | Condor v2.0 |
| 🐆 [JAGUAR](./jaguar) | v1.0 | -29.3% | Jaguar v2.0 |
| 🦈 [SHARK](./shark) | v1.0 | -4.6% | Shark v2.0 |
| 🦅 [BALD EAGLE](./bald-eagle) | v1.0 | -28.6% | Bald Eagle v2.0 |
| 🦊 [VIXEN](./vixen) | v1.0 | -47.3% | Orca v1.2 |
| 👻 [Ghost Fox](./ghost-fox-strategy) | v2.0 | -58.5% | Orca v1.2 |
| 🦊 [Feral Fox](./feral-fox-v3-strategy.md) | v3.0 | -31.5% | Orca v1.2 |
| 🐺 [Dire Wolf](./wolf-strategy) | v1.0 | -42.3% | Orca v1.2 |
| 🐍 [COBRA](./cobra) | v2.0 | -53.0% | Retired |
| 🐍 [MAMBA](./mamba) | v1.0 | -36.8% | Retired |
| 🐍 [ANACONDA](./anaconda) | v1.0 | -21.9% | Retired |
| 🐍 [VIPER](./viper) | v1.0 | -19.9% | Retired |
| 🐺 [JACKAL](./jackal) | v2.0 | -32.8% | Retired |
| 🦂 [SCORPION](./scorpion) | v2.0 | -21.1% | Retired |
| 🐅 [TIGER](./tiger-strategy) | v1.0 | -58.0% | Retired |
| 🐊 [CROC](./croc) | v1.0 | -42.9% | Retired |
| 🐊 [GATOR](./gator) | v1.0 | N/A | Retired |

---

## Lessons from 30+ Live Agents

### The Proven Pattern

**Fewer trades + higher conviction + wider stops = better performance.**

| Agent | Trades | ROE | The Lesson |
|---|---|---|---|
| 🐻‍❄️ Polar | 71 | **+23.6%** | Single asset, lifecycle patience, wide stops |
| 🪳 Roach | 100 | **+5.3%** | Striker-only, highest conviction entries |
| 🦗 Mantis | 460 | **+5.6%** | SM quality gate, moderate frequency |
| 👻 Ghost Fox | 1,078 | **-58.5%** | Over-trading kills |
| 🐅 Tiger | 726 | **-58.0%** | More scanners ≠ better results |

### The #1 Bug: Missing DSL Wallet Fields

8 agents lost a combined **$3,000+** from the same root cause: the Python scanner generates a DSL state file without `wallet` and `strategyWalletAddress` fields, so dsl-v5.py can't match the state file to the on-chain position, and the position runs unprotected.

Agents hit: Jaguar, Condor, Bald Eagle, Wolverine, Orca v1.2, Fox, Hydra, Grizzly.

**Fix:** All v2.0 scanners include wallet fields in DSL state. The DSL plugin (shipping soon) eliminates state files entirely.

### Thesis Exit Kills Winners

When the scanner re-evaluates open positions and closes them on "thesis invalidation," it chops winners before DSL can trail them. Wolverine v1.1 lost -23.4% because the scanner killed 25 of 27 trades. The one trade it let run (+29.9% ROE) was worth more than all other winners combined.

**Fix:** All v2.0 scanners output `NO_REPLY` when a position is active. DSL is the only exit mechanism.

### Fee Bleed from Rapid Cycling

Orca v1.1 had +$136 gross P&L across 3 days — the scanner finds real edge. But $279 in exchange fees from 80 trades ate all the profit. DSL stops out quickly → slot opens → scanner re-enters immediately → fees compound.

**Fix:** `MAX_ENTRIES_PER_DAY` hardcoded in every v2.0 scanner.

---

## DSL v1.1.1 Pattern (Mandatory)

Every active skill uses this DSL state pattern. If any field is wrong, the agent is running with broken safety.

```json
{
  "active": true,
  "wallet": "<strategy_wallet_address>",
  "strategyWalletAddress": "<strategy_wallet_address>",
  "strategyId": "<strategy_id>",
  "size": null,
  "highWaterPrice": null,
  "highWaterRoe": null,
  "phase1": {
    "consecutiveBreachesRequired": 3,
    "phase1MaxMinutes": 25,
    "deadWeightCutMin": 8,
    "absoluteFloorRoe": -18,
    "retraceThreshold": 0.08
  }
}
```

Critical fields — get these wrong and positions bleed silently:
- `wallet` and `strategyWalletAddress` — **MUST be present** or DSL skips the position entirely
- `size` — agent MUST set from clearinghouse after entry fills, or DSL crashes
- `phase1MaxMinutes` (NOT hardTimeoutMinutes)
- `deadWeightCutMin` (NOT deadWeightCutMinutes)
- `absoluteFloorRoe` (NOT absoluteFloor — no static price values)
- `highWaterPrice: null` (NOT 0)
- `consecutiveBreachesRequired: 3` (NOT 1)

---

## Architecture

```
Plugins ──→ Skills ──→ Agents
(shared)     (scanner)   (deployed instance)
```

**Plugins** are shared infrastructure — trailing stops, risk management, fee optimization. Maintained once, every skill benefits.

**Skills** are the trading logic — the scanner that embodies a thesis about how to make money. Each skill is a self-contained directory with a scanner, config helper, configuration, and SKILL.md that the agent reads as its operating instructions.

**Agents** are deployed instances of skills running with real capital on the Senpi Predators arena. Multiple agents can run the same skill with different parameters.

---

## Quick Start

1. Deploy [OpenClaw](https://openclaw.ai) with [Senpi](https://senpi.ai) MCP configured
2. Install a skill: `npx skills add Senpi-ai/senpi-skills/<skill-name>`
3. The agent reads SKILL.md, runs bootstrap, creates crons, and starts trading
4. Monitor via Telegram alerts and [strategies.senpi.ai](https://strategies.senpi.ai)

**Recommended first skill:** [ROACH v1.0](./roach) — Striker-only, highest conviction entries, simplest architecture, best risk-adjusted performance in the fleet.

## Requirements

- [OpenClaw](https://openclaw.ai) agent with cron support
- [Senpi](https://senpi.ai) MCP access token
- Python 3.8+ (no external dependencies — all skills use stdlib only)

## Contributing

Each skill is self-contained in its own directory. See any skill's SKILL.md for the full agent instructions. All active skills use [DSL High Water Mode](./dsl-dynamic-stop-loss/dsl-high-water-spec%201.0.md) as the target trailing stop configuration.

**When adding a new skill**, add an entry to [`catalog.json`](./catalog.json).

## License

MIT — Built by [Senpi](https://senpi.ai).
