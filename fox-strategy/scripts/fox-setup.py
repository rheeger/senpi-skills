#!/usr/bin/env python3
"""
FOX v0.2 Setup Wizard
Sets up a FOX autonomous trading strategy and adds it to the multi-strategy registry.
Calculates all parameters from budget, fetches max-leverage data,
creates trade counter file, and outputs config + cron templates.

Usage:
  # Agent passes what it knows, only asks user for budget:
  python3 fox-setup.py --wallet 0x... --strategy-id UUID --chat-id 12345 --budget 6500

  # With provider, trading risk, and custom name:
  python3 fox-setup.py --wallet 0x... --strategy-id UUID --chat-id 12345 --budget 6500 \
      --provider openai --trading-risk aggressive --name "Aggressive Momentum"

  # Interactive mode (prompts for everything):
  python3 fox-setup.py
"""
import json, sys, os, math, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fox_config import mcporter_call, atomic_write

WORKSPACE = os.environ.get("FOX_WORKSPACE",
    os.environ.get("OPENCLAW_WORKSPACE", "/data/workspace"))
REGISTRY_FILE = os.path.join(WORKSPACE, "fox-strategies.json")
LEGACY_CONFIG = os.path.join(WORKSPACE, "fox-strategy.json")
MAX_LEV_FILE = os.path.join(WORKSPACE, "max-leverage.json")
TRADE_COUNTER_FILE = os.path.join(WORKSPACE, "fox-trade-counter.json")
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Provider -> model mapping
PROVIDER_MODELS = {
    "anthropic": {"mid": "anthropic/claude-sonnet-4-5", "budget": "anthropic/claude-haiku-4-5"},
    "openai":    {"mid": "openai/gpt-4o",               "budget": "openai/gpt-4o-mini"},
    "google":    {"mid": "google/gemini-2.0-flash",      "budget": "google/gemini-2.0-flash-lite"},
}

# DSL presets — 9-tier v5 format (from state-schema.md)
DSL_PRESETS = {
    "aggressive": [
        {"triggerPct": 5, "lockPct": 2, "breaches": 2},
        {"triggerPct": 10, "lockPct": 5, "breaches": 2},
        {"triggerPct": 20, "lockPct": 14, "breaches": 2},
        {"triggerPct": 30, "lockPct": 24, "breaches": 2},
        {"triggerPct": 40, "lockPct": 34, "breaches": 1},
        {"triggerPct": 50, "lockPct": 44, "breaches": 1},
        {"triggerPct": 65, "lockPct": 56, "breaches": 1},
        {"triggerPct": 80, "lockPct": 72, "breaches": 1},
        {"triggerPct": 100, "lockPct": 90, "breaches": 1},
    ],
    "conservative": [
        {"triggerPct": 3, "lockPct": 1, "breaches": 3},
        {"triggerPct": 7, "lockPct": 3, "breaches": 3},
        {"triggerPct": 15, "lockPct": 10, "breaches": 2},
        {"triggerPct": 25, "lockPct": 18, "breaches": 2},
        {"triggerPct": 35, "lockPct": 28, "breaches": 2},
        {"triggerPct": 45, "lockPct": 38, "breaches": 1},
        {"triggerPct": 55, "lockPct": 48, "breaches": 1},
        {"triggerPct": 70, "lockPct": 62, "breaches": 1},
        {"triggerPct": 90, "lockPct": 82, "breaches": 1},
    ]
}

# Parse CLI args
parser = argparse.ArgumentParser(description="FOX v0.2 Setup")
parser.add_argument("--wallet", help="Strategy wallet address (0x...)")
parser.add_argument("--strategy-id", help="Strategy ID (UUID)")
parser.add_argument("--budget", type=float, help="Trading budget in USD (min $500)")
parser.add_argument("--chat-id", type=int, help="Telegram chat ID")
parser.add_argument("--name", help="Human-readable strategy name (optional)")
parser.add_argument("--dsl-preset", choices=["aggressive", "conservative"], default="aggressive",
                    help="DSL tier preset (default: aggressive)")
parser.add_argument("--provider", choices=list(PROVIDER_MODELS.keys()),
                    default="anthropic",
                    help="LLM provider for cron models (default: anthropic)")
parser.add_argument("--trading-risk", choices=["conservative", "moderate", "aggressive"],
                    default="moderate",
                    help="Trading risk profile (default: moderate)")
parser.add_argument("--mid-model", default=None,
                    help="Override mid-tier model (default: auto from --provider)")
parser.add_argument("--budget-model", default=None,
                    help="Override budget-tier model (default: auto from --provider)")
args = parser.parse_args()


def ask(prompt, default=None, validator=None):
    while True:
        suffix = f" [{default}]" if default else ""
        val = input(f"{prompt}{suffix}: ").strip()
        if not val and default:
            val = str(default)
        if validator:
            try:
                return validator(val)
            except Exception as e:
                print(f"  Invalid: {e}")
        elif val:
            return val
        else:
            print("  Required.")


def validate_wallet(v):
    if not v.startswith("0x") or len(v) != 42:
        raise ValueError("Must be 0x... (42 chars)")
    return v


def validate_uuid(v):
    parts = v.replace("-", "")
    if len(parts) != 32:
        raise ValueError("Must be a UUID (32 hex chars)")
    return v


def validate_budget(v):
    b = float(v)
    if b < 500:
        raise ValueError("Minimum budget is $500")
    return b


def validate_chat_id(v):
    return int(v)


print("=" * 60)
print("  FOX v0.2 -- Autonomous Trading Strategy Setup")
print("=" * 60)
print()

# Use CLI args if provided, otherwise prompt
wallet = args.wallet or ask("Strategy wallet address (0x...)", validator=validate_wallet)
if args.wallet:
    validate_wallet(args.wallet)

strategy_id = args.strategy_id or ask("Strategy ID (UUID)", validator=validate_uuid)
if args.strategy_id:
    validate_uuid(args.strategy_id)

budget = args.budget or ask("Trading budget (USD, min $500)", validator=validate_budget)
if args.budget:
    validate_budget(str(args.budget))

chat_id = args.chat_id or ask("Telegram chat ID (numeric)", validator=validate_chat_id)
if args.chat_id:
    validate_chat_id(str(args.chat_id))

strategy_name = args.name or f"Strategy {strategy_id[:8]}"
dsl_preset = args.dsl_preset
trading_risk = args.trading_risk

# Resolve models from provider (CLI overrides take priority)
provider_models = PROVIDER_MODELS[args.provider]
mid_model = args.mid_model or provider_models["mid"]
budget_model = args.budget_model or provider_models["budget"]

# Calculate parameters
# Tiered margin: percentage of budget per entry, decreasing as more positions open
MARGIN_TIERS = [
    {"entries": [1, 2], "marginPct": 0.22},  # 22% of budget per trade (44% total)
    {"entries": [3, 4], "marginPct": 0.15},  # 15% of budget per trade (30% total)
    {"entries": [5, 6], "marginPct": 0.07},  # 7% of budget per trade (14% total)
]
# Total at max fill: 88% of budget. 12% buffer for fees/slippage/drawdown.

max_entries = 6
daily_loss_limit = round(budget * 0.15, 2)
drawdown_cap = round(budget * 0.30, 2)

# Slots based on budget
if budget < 1000:
    slots = 2
elif budget < 3000:
    slots = 3
elif budget < 8000:
    slots = 4
elif budget < 15000:
    slots = 5
else:
    slots = 6

if budget < 1000:
    default_leverage = 5
elif budget < 5000:
    default_leverage = 7
elif budget < 15000:
    default_leverage = 10
else:
    default_leverage = 10

# Pre-calculate dollar amounts from percentages for convenience
margin_tiers_with_amounts = []
for tier in MARGIN_TIERS:
    margin_amount = round(budget * tier["marginPct"], 2)
    margin_tiers_with_amounts.append({
        "entries": tier["entries"],
        "marginPct": tier["marginPct"],
        "margin": margin_amount,
    })

# Use tier 1 margin as the representative "margin per slot" for display
margin_per_slot = margin_tiers_with_amounts[0]["margin"]
notional_per_slot = round(margin_per_slot * default_leverage, 2)
auto_delever_threshold = round(budget * 0.80, 2)

# Build strategy key
strategy_key = f"fox-{strategy_id[:8]}"

# Build strategy entry
strategy_entry = {
    "name": strategy_name,
    "wallet": wallet,
    "strategyId": strategy_id,
    "budget": budget,
    "slots": slots,
    "maxEntries": max_entries,
    "marginTiers": margin_tiers_with_amounts,
    "marginPerSlot": margin_per_slot,
    "defaultLeverage": default_leverage,
    "tradingRisk": trading_risk,
    "dailyLossLimit": daily_loss_limit,
    "autoDeleverThreshold": auto_delever_threshold,
    "dsl": {
        "preset": dsl_preset,
        "tiers": DSL_PRESETS[dsl_preset]
    },
    "enabled": True
}

# Load or create registry
if os.path.exists(REGISTRY_FILE):
    with open(REGISTRY_FILE) as f:
        registry = json.load(f)
else:
    registry = {
        "version": 1,
        "defaultStrategy": None,
        "strategies": {},
        "global": {
            "telegramChatId": str(chat_id),
            "workspace": WORKSPACE,
            "notifications": {
                "provider": "telegram",
                "alertDedupeMinutes": 15
            }
        }
    }

# Add strategy to registry
registry["strategies"][strategy_key] = strategy_entry

# Set as default if it's the only one (or the first)
if registry.get("defaultStrategy") is None or len(registry["strategies"]) == 1:
    registry["defaultStrategy"] = strategy_key

# Update global telegram if needed
if not registry["global"].get("telegramChatId"):
    registry["global"]["telegramChatId"] = str(chat_id)

# Save registry atomically
os.makedirs(WORKSPACE, exist_ok=True)
atomic_write(REGISTRY_FILE, registry)
print(f"\n  Registry saved to {REGISTRY_FILE}")

# Create per-strategy state directory
state_dir = os.path.join(WORKSPACE, "state", strategy_key)
os.makedirs(state_dir, exist_ok=True)
print(f"  State directory created: {state_dir}")

# Create other shared directories
for d in ["history", "memory", "logs"]:
    os.makedirs(os.path.join(WORKSPACE, d), exist_ok=True)

# Create trade counter file if it doesn't exist
if not os.path.exists(TRADE_COUNTER_FILE):
    trade_counter = {
        "entries": 0,
        "marginTiers": margin_tiers_with_amounts,
        "budget": budget,
        "lastUpdated": None
    }
    atomic_write(TRADE_COUNTER_FILE, trade_counter)
    print(f"  Trade counter created: {TRADE_COUNTER_FILE}")
else:
    print(f"  Trade counter exists: {TRADE_COUNTER_FILE}")

# Fetch max-leverage via MCP (covers both crypto and XYZ instruments)
print("\nFetching max-leverage data...")
try:
    data = mcporter_call("market_list_instruments")
    instruments = data.get("instruments", [])
    if not isinstance(instruments, list):
        instruments = []
    max_lev = {}
    for inst in instruments:
        if not isinstance(inst, dict):
            continue
        name = inst.get("name", "")
        if not name:
            continue
        lev = inst.get("max_leverage") or inst.get("maxLeverage")
        if lev is not None:
            max_lev[name] = int(lev)
    atomic_write(MAX_LEV_FILE, max_lev)
    crypto_count = sum(1 for inst in instruments if isinstance(inst, dict) and not inst.get("dex"))
    xyz_count = sum(1 for inst in instruments if isinstance(inst, dict) and inst.get("dex"))
    print(f"  Max leverage data saved ({len(max_lev)} assets: {crypto_count} crypto, {xyz_count} XYZ) to {MAX_LEV_FILE}")
except Exception as e:
    print(f"  Failed to fetch max-leverage: {e}")
    print("  You can manually fetch later.")

# Build cron templates — ALL isolated/agentTurn with simplified mandates
tg = f"telegram:{chat_id}"

cron_templates = {
    "emerging_movers": {
        "name": "FOX Emerging Movers (3min)",
        "schedule": {"kind": "every", "everyMs": 180000},
        "sessionTarget": "isolated",
        "payload": {
            "kind": "agentTurn",
            "model": mid_model,
            "message": (
                f"FOX Scanner: Run `PYTHONUNBUFFERED=1 python3 {SCRIPTS_DIR}/fox-emerging-movers.py`, parse JSON.\n"
                f"SLOT GUARD: If `anySlotsAvailable` is false AND `hasFirstJump` is false -> HEARTBEAT_OK.\n"
                f"Act ONLY on `topPicks` array. Process topPicks[0] first, then topPicks[1], etc.\n"
                f"Enter via: `python3 {SCRIPTS_DIR}/fox-open-position.py --strategy {{strategyKey}} --asset {{qualifiedAsset}} --signal-index {{signalIndex}}`\n"
                f"The `qualifiedAsset` field includes `xyz:` prefix for XYZ equities. Use it directly.\n"
                f"ROTATION: Only rotate coins in `strategySlots[strategy].rotationEligibleCoins`. "
                f"If `hasRotationCandidate` is false -> skip rotation. Add `--close-asset {{coin}}` to rotate.\n"
                f"For each successful entry, send each message in `notifications` from open-position.py output to {tg}.\n"
                f"If no actionable signals -> HEARTBEAT_OK."
            )
        }
    },
    "dsl_combined": {
        "name": "FOX DSL Combined (3min)",
        "schedule": {"kind": "every", "everyMs": 180000},
        "sessionTarget": "isolated",
        "payload": {
            "kind": "agentTurn",
            "model": mid_model,
            "message": (
                f"FOX DSL: Run `PYTHONUNBUFFERED=1 python3 {SCRIPTS_DIR}/fox-dsl-wrapper.py`, parse JSON.\n"
                f"For each item in `action_required`: close that position (coin + strategyKey wallet), alert {tg}.\n"
                f"Send each message in `notifications` to {tg}.\n"
                f"If both empty -> HEARTBEAT_OK."
            )
        }
    },
    "sm_flip": {
        "name": "FOX SM Flip Detector (5min)",
        "schedule": {"kind": "every", "everyMs": 300000},
        "sessionTarget": "isolated",
        "payload": {
            "kind": "agentTurn",
            "model": budget_model,
            "message": (
                f"FOX SM: Run `python3 {SCRIPTS_DIR}/fox-sm-flip-check.py`, parse JSON.\n"
                f"For each item in `action_required`: close that position (coin + strategyKey wallet), alert {tg}.\n"
                f"Send each message in `notifications` to {tg}.\n"
                f"If both empty -> HEARTBEAT_OK."
            )
        }
    },
    "watchdog": {
        "name": "FOX Watchdog (5min)",
        "schedule": {"kind": "every", "everyMs": 300000},
        "sessionTarget": "isolated",
        "payload": {
            "kind": "agentTurn",
            "model": budget_model,
            "message": (
                f"FOX Watchdog: Run `PYTHONUNBUFFERED=1 timeout 45 python3 {SCRIPTS_DIR}/fox-monitor.py`, parse JSON.\n"
                f"For each item in `action_required`: close the specified position (coin + strategyKey), alert {tg}.\n"
                f"Send each message in `notifications` to {tg}.\n"
                f"If both empty -> HEARTBEAT_OK."
            )
        }
    },
    "portfolio": {
        "name": "FOX Portfolio (15min)",
        "schedule": {"kind": "every", "everyMs": 900000},
        "sessionTarget": "isolated",
        "payload": {
            "kind": "agentTurn",
            "model": mid_model,
            "message": (
                f"FOX Portfolio: Read {WORKSPACE}/fox-strategies.json. For each enabled strategy, "
                f"call `strategy_get_clearinghouse_state` with the strategy wallet.\n"
                f"Format a code-block table with: per-strategy name, account value, positions "
                f"(asset, direction, ROE%, PnL, DSL tier), slot usage, and global totals.\n"
                f"Send to {tg}."
            )
        }
    },
    "health_check": {
        "name": "FOX Health Check (10min)",
        "schedule": {"kind": "every", "everyMs": 600000},
        "sessionTarget": "isolated",
        "payload": {
            "kind": "agentTurn",
            "model": mid_model,
            "message": (
                f"FOX Health: Run `PYTHONUNBUFFERED=1 python3 {SCRIPTS_DIR}/fox-health-check.py`, parse JSON.\n"
                f"Send each message in `notifications` to {tg}.\n"
                f"If `notifications` is empty -> HEARTBEAT_OK."
            )
        }
    },
    "opportunity_scanner": {
        "name": "FOX Opportunity Scanner (15min)",
        "schedule": {"kind": "every", "everyMs": 900000},
        "sessionTarget": "isolated",
        "payload": {
            "kind": "agentTurn",
            "model": mid_model,
            "message": (
                f"FOX Scanner: Run `PYTHONUNBUFFERED=1 timeout 180 python3 {SCRIPTS_DIR}/fox-opportunity-scan-v6.py`, parse JSON.\n"
                f"SLOT GUARD: If `anySlotsAvailable` is false -> HEARTBEAT_OK.\n"
                f"For each opportunity in `topPicks`: enter via "
                f"`python3 {SCRIPTS_DIR}/fox-open-position.py --strategy {{strategyKey}} --asset {{qualifiedAsset}} --signal-index {{signalIndex}}`.\n"
                f"Send each message in `notifications` to {tg}. Else HEARTBEAT_OK."
            )
        }
    },
    "market_regime": {
        "name": "FOX Market Regime (4h)",
        "schedule": {"kind": "every", "everyMs": 14400000},
        "sessionTarget": "isolated",
        "payload": {
            "kind": "agentTurn",
            "model": mid_model,
            "message": (
                f"FOX Regime: Run `PYTHONUNBUFFERED=1 python3 {SCRIPTS_DIR}/fox-market-regime.py`, parse JSON.\n"
                f"Save the full output to `{WORKSPACE}/market-regime-last.json`.\n"
                f"HEARTBEAT_OK after saving."
            )
        }
    }
}

print("\n" + "=" * 60)
print("  FOX v0.2 Configuration Summary")
print("=" * 60)
print(f"""
  Strategy Key:     {strategy_key}
  Strategy Name:    {strategy_name}
  Wallet:           {wallet}
  Strategy ID:      {strategy_id}
  Budget:           ${budget:,.2f}
  Slots:            {slots}
  Trading Risk:     {trading_risk}
  Margin/Slot:      ${margin_per_slot:,.2f}
  Default Leverage:  {default_leverage}x
  Notional/Slot:    ${notional_per_slot:,.2f}
  Daily Loss Limit: ${daily_loss_limit:,.2f}
  Auto-Delever:     Below ${auto_delever_threshold:,.2f}
  DSL Preset:       {dsl_preset} (9-tier v5)
  Provider:         {args.provider}
  Mid Model:        {mid_model}
  Budget Model:     {budget_model}
  Telegram:         {tg}
""")

strategies_count = len(registry["strategies"])
print(f"  Total strategies in registry: {strategies_count}")
if strategies_count > 1:
    print(f"  All strategies: {list(registry['strategies'].keys())}")

print("\n" + "=" * 60)
print("  Next Steps: Create 8 cron jobs")
print("=" * 60)
print(f"""
Use OpenClaw cron to create each job. See references/cron-templates.md
for the exact payload text for each of the 8 jobs.

With multi-strategy, crons iterate all enabled strategies internally.
You only need ONE set of crons regardless of strategy count.

  ALL crons are isolated/agentTurn (no main session crons):
  +------------------------+----------+---------+-------------------------------------------+
  | Cron                   | Interval | Tier    | Model                                     |
  +------------------------+----------+---------+-------------------------------------------+
  | Emerging Movers        | 3min     | Mid     | {mid_model:<41} |
  | DSL Combined           | 3min     | Mid     | {mid_model:<41} |
  | Opportunity Scanner    | 15min    | Mid     | {mid_model:<41} |
  | Portfolio Update       | 15min    | Mid     | {mid_model:<41} |
  | Health Check           | 10min    | Mid     | {mid_model:<41} |
  | Market Regime          | 4h       | Mid     | {mid_model:<41} |
  | SM Flip Detector       | 5min     | Budget  | {budget_model:<41} |
  | Watchdog               | 5min     | Budget  | {budget_model:<41} |
  +------------------------+----------+---------+-------------------------------------------+
""")

# Output full result as JSON for programmatic use
result = {
    "success": True,
    "strategyKey": strategy_key,
    "config": strategy_entry,
    "registry": {
        "strategiesCount": strategies_count,
        "strategies": list(registry["strategies"].keys()),
        "defaultStrategy": registry["defaultStrategy"]
    },
    "cronTemplates": cron_templates,
    "maxLeverageFile": MAX_LEV_FILE,
    "tradeCounterFile": TRADE_COUNTER_FILE,
    "registryFile": REGISTRY_FILE,
    "stateDir": state_dir,
}
print(json.dumps(result, indent=2))
