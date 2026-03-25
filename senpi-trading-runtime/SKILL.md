---
name: senpi-trading-runtime
description: "Configure, deploy, and manage trading recipes in the Senpi Trading Runtime OpenClaw plugin for automated on-chain position tracking with DSL trailing stop-loss protection. Use when a user needs to create or modify trading recipe YAML files, configure DSL (Dynamic Stop-Loss) exit engine parameters (phases, tiers, time-based cuts), set up the position_tracker scanner to monitor a wallet's positions on Hyperliquid, install/list/delete recipes via CLI, or inspect DSL-tracked positions. Triggers on mentions of senpi, trading recipe, DSL exit, stop-loss tiers, position tracker, trailing stop, openclaw senpi, dsl_preset, or strategy YAML configuration."
---

# Senpi Trading Runtime — OpenClaw Plugin

On-chain position tracker with automated DSL (Dynamic Stop-Loss) exit engine. Monitors a wallet's positions on Hyperliquid for lifecycle events (open, close, edit, flip) and applies two-phase trailing stop-loss protection to all positions.

## Core Concepts

**Flow:** Position Tracker scanner → detects position changes → DSL exit engine manages trailing stops

1. **Position Tracker** (`position_tracker` scanner) polls the wallet on-chain, detecting opens, closes, increases, decreases, and flips.
2. **DSL exit engine** monitors tracked positions on a timer, computing trailing stop-loss floors across two phases.
3. **Strategy** = a wallet address. The wallet address is the strategy identifier everywhere.

**Key insight:** The position tracker enables DSL protection for ALL positions of a strategy address — including those opened manually on the exchange or by other tools.

## CLI Commands

All commands require the OpenClaw gateway running (`openclaw gateway run`).

### Recipe management

```bash
# Create a recipe from YAML file
openclaw senpi trading-recipe create --path ./my-strategy.yaml

# Create with inline YAML content
openclaw senpi trading-recipe create --content "<yaml>"

# Create with custom ID
openclaw senpi trading-recipe create --path ./my-strategy.yaml --recipe-id my-name

# List installed recipes (id, source, status)
openclaw senpi trading-recipe list

# Delete a recipe
openclaw senpi trading-recipe delete <recipe_id>
```

### DSL position inspection

```bash
# All active DSL-tracked positions
openclaw senpi dsl positions
openclaw senpi dsl positions --recipe <id>
openclaw senpi dsl positions --address <0x...>
openclaw senpi dsl positions --json

# Inspect one position (full DslState)
openclaw senpi dsl inspect <ASSET>
openclaw senpi dsl inspect SOL --recipe <id>
openclaw senpi dsl inspect BTC --json

# Archived (closed) positions
openclaw senpi dsl closes
openclaw senpi dsl closes --limit 20 --json
```

### In-shell reference

```bash
openclaw senpi guide              # Overview and quick command list
openclaw senpi guide dsl          # DSL exit engine reference
openclaw senpi guide examples     # Print minimal strategy YAML
openclaw senpi guide schema       # Full YAML schema
```

### Configuration

```bash
openclaw senpi config set-chat-id <chatId>           # Telegram notifications
openclaw senpi config set-senpi-jwt-token <token>     # Senpi MCP auth
openclaw senpi config set-state-dir <dir>             # State directory
openclaw senpi config get <key>
openclaw senpi config list
openclaw senpi config unset <key>
openclaw senpi config reset
```

### Gateway RPC (advanced)

```bash
openclaw gateway call senpi.listDslPositions --json --params '{}'
openclaw gateway call senpi.getDslPositionState --json --params '{"asset":"SOL"}'
openclaw gateway call senpi.listDslArchives --json --params '{"limit":20}'
openclaw gateway call senpi.installRecipe --params '{"tradingRecipeYamlContent":"..."}'
openclaw gateway call senpi.listRecipes --json --params '{}'
openclaw gateway call senpi.deleteRecipe --params '{"id":"my-recipe"}'
```

## Trading Recipe YAML

The recipe YAML drives all behavior. Top-level keys: `name`, `strategies`, `scanners`, `actions`, `exit`, `notifications`.

```yaml
name: my-tracker
version: 1.0.0
description: >
  On-chain position tracker with DSL trailing stop-loss.

strategies:
  main:
    wallet: "${WALLET_ADDRESS}"
    budget: 500
    slots: 2
    margin_per_slot: 200
    trading_risk: conservative    # conservative | moderate | aggressive
    enabled: true

scanners:
  - name: position_tracker
    type: position_tracker
    interval: 10s

actions:
  - name: position_tracker_action
    action_type: POSITION_TRACKER
    decision_mode: rule
    scanners: [position_tracker]

exit:
  engine: dsl
  interval_seconds: 30            # how often the price monitor runs (5-3600)
  dsl_preset:                     # single preset (no named map needed)
    hard_timeout:
      enabled: true
      interval_in_minutes: 360
    weak_peak_cut:
      enabled: true
      interval_in_minutes: 120
      min_value: 5
    dead_weight_cut:
      enabled: true
      interval_in_minutes: 60
    phase1:
      enabled: true
      max_loss_pct: 4.0
      retrace_threshold: 7
      consecutive_breaches_required: 1
    phase2:
      enabled: true
      tiers:
        - { trigger_pct: 7,  lock_hw_pct: 40 }
        - { trigger_pct: 12, lock_hw_pct: 55 }
        - { trigger_pct: 15, lock_hw_pct: 75 }
        - { trigger_pct: 20, lock_hw_pct: 85 }

notifications:
  telegram_chat_id: "${TELEGRAM_CHAT_ID}"
```

Environment variable substitution: `${VAR}` and `${VAR:-default}` resolved at load time.

For full field details: [YAML Schema Reference](references/yaml-schema.md)

## DSL Exit Engine — Key Concepts

**Two-phase trailing stop-loss** protecting open positions:

**Phase 1** (from entry until the first tier is reached):
- **Absolute floor** from `max_loss_pct` (cap on loss from entry, scaled by leverage)
- **Trailing floor** from `retrace_threshold` (ROE % pullback from high-water mark)
- Effective floor = stricter of both (LONG: higher price; SHORT: lower)
- Optional **time-based cuts** at preset level: `hard_timeout`, `weak_peak_cut`, `dead_weight_cut`
- Exchange SL stays at the absolute floor only; tighter exits enforced by runtime

**Phase 2** (after the first tier is reached — Phase 2 always starts at tier 0):
- **Tier floor** = `lock_hw_pct` % of current high-water ROE (trails as HW advances, never loosens)
- Exchange SL tracks the full effective floor and updates as it moves

**Tiers** are profit milestones (by ROE % from entry). Each tier has two fields: `trigger_pct` (ROE % that activates it) and `lock_hw_pct` (% of high-water ROE to lock as floor). Tiers must have strictly increasing `trigger_pct`.

**Consecutive breaches** are tick-based (not time-based). Each monitor tick (every `interval_seconds`), if price violates the floor, the breach counter increments. Recovery resets it.

**Retrace convention:** `retrace_threshold` is ROE %. Engine converts to price: `retrace_ROE% / 100 / leverage`. At 10x leverage, 7% ROE retrace = 0.7% price below high-water.

For full DSL configuration with all fields, time-based cuts, close reasons, and events: [DSL Configuration Reference](references/dsl-configuration.md)

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `WALLET_ADDRESS` | Yes | Strategy wallet address (used in YAML via `${WALLET_ADDRESS}`). |
| `SENPI_API_KEY` | For live MCP | Senpi MCP authentication. |
| `TELEGRAM_CHAT_ID` | No | Telegram chat ID for notifications. |
| `DSL_STATE_DIR` | No | Override DSL state file directory. |

## References

- [YAML Schema Reference](references/yaml-schema.md) — All recipe fields and DSL preset options
- [DSL Configuration Reference](references/dsl-configuration.md) — Full DSL exit engine: phases, tiers, time cuts, close reasons, events
- [Strategy Examples](references/strategy-examples.md) — Ready-to-use YAML recipes with different DSL tuning profiles
