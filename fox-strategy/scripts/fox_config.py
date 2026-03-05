#!/usr/bin/env python3
"""
fox_config.py — Multi-strategy config loader for FOX v0.2

Provides a single importable module every script uses to load strategy config,
resolve state file paths, and handle legacy migration.

Usage:
    from fox_config import load_strategy, load_all_strategies, dsl_state_path
    cfg = load_strategy("fox-abc123")   # Specific strategy
    cfg = load_strategy()                # Default strategy
    strategies = load_all_strategies()   # All enabled strategies
    path = dsl_state_path("fox-abc123", "HYPE")
"""

import json, os, sys, glob, time
from contextlib import contextmanager

# ─── Import shared utilities from senpi_lib ──────────────────────────────────
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
SKILLS_ROOT = os.path.dirname(SKILL_DIR)
sys.path.insert(0, os.path.join(SKILLS_ROOT, "shared"))

from senpi_lib import (mcporter_call, mcporter_call_safe, atomic_write, fail_json,
                        strategy_lock as _strategy_lock_base, heartbeat_write,
                        send_notification_to_telegram, calculate_leverage,
                        validate_dsl_state, extract_positions_from_section,
                        get_wallet_positions, extract_single_position,
                        count_active_dsls, load_strategy_registry,
                        load_strategy_from_registry, load_all_from_registry,
                        make_state_dir, make_dsl_state_path, make_dsl_state_glob,
                        get_all_active_positions_base,
                        RISK_LEVERAGE_RANGES, SIGNAL_CONVICTION,
                        ROTATION_COOLDOWN_MINUTES)

# ─── FOX-specific paths ──────────────────────────────────────────────────────

WORKSPACE = os.environ.get("FOX_WORKSPACE",
    os.environ.get("OPENCLAW_WORKSPACE", "/data/workspace"))
REGISTRY_FILE = os.path.join(WORKSPACE, "fox-strategies.json")
LEGACY_CONFIG = os.path.join(WORKSPACE, "fox-strategy.json")
LEGACY_STATE_PATTERN = os.path.join(WORKSPACE, "dsl-state-FOX-*.json")
HEARTBEAT_FILE = os.path.join(WORKSPACE, "state", "cron-heartbeats.json")

# Re-export fail_json as _fail for backward compat
_fail = fail_json


def _migrate_legacy_state_files(strategy_key):
    """Move old dsl-state-FOX-*.json files into state/{strategy_key}/dsl-*.json."""
    legacy_files = glob.glob(LEGACY_STATE_PATTERN)
    if not legacy_files:
        return

    new_dir = os.path.join(WORKSPACE, "state", strategy_key)
    os.makedirs(new_dir, exist_ok=True)

    for old_path in legacy_files:
        basename = os.path.basename(old_path)
        # dsl-state-FOX-HYPE.json → dsl-HYPE.json
        asset = basename.replace("dsl-state-FOX-", "").replace(".json", "")
        new_path = os.path.join(new_dir, f"dsl-{asset}.json")

        if os.path.exists(new_path):
            continue

        try:
            with open(old_path) as f:
                state = json.load(f)
            state["strategyKey"] = strategy_key
            if "version" not in state:
                state["version"] = 2
            atomic_write(new_path, state)
        except (json.JSONDecodeError, IOError):
            continue


def _load_registry():
    """Load the strategy registry, with auto-migration from legacy format."""
    result = load_strategy_registry(REGISTRY_FILE, legacy_config=LEGACY_CONFIG, retry=True)
    if result is not None:
        return result

    # Legacy migration (senpi_lib returned None signaling legacy fallback)
    with open(LEGACY_CONFIG) as f:
        legacy = json.load(f)
    sid = legacy.get("strategyId", "unknown")
    key = f"fox-{sid[:8]}" if sid != "unknown" else "fox-default"

    strategy = {
        "name": "Default Strategy",
        "wallet": legacy.get("wallet", ""),
        "strategyId": legacy.get("strategyId", ""),
        "budget": legacy.get("budget", 0),
        "slots": legacy.get("slots", 2),
        "marginPerSlot": legacy.get("marginPerSlot", 0),
        "defaultLeverage": legacy.get("defaultLeverage", 10),
        "dailyLossLimit": legacy.get("dailyLossLimit", 0),
        "autoDeleverThreshold": legacy.get("autoDeleverThreshold", 0),
        "dsl": {
            "preset": "aggressive",
            "tiers": FOX_DEFAULT_TIERS
        },
        "enabled": True
    }

    registry = {
        "version": 1,
        "defaultStrategy": key,
        "strategies": {key: strategy},
        "global": {
            "telegramChatId": str(legacy.get("telegramChatId", "")),
            "workspace": WORKSPACE,
            "notifications": {
                "provider": "telegram",
                "alertDedupeMinutes": 15
            }
        }
    }

    _migrate_legacy_state_files(key)
    return registry


# ─── Thin wrappers that inject FOX paths ──────────────────────────────────────

def load_strategy(strategy_key=None):
    """Load a single strategy config."""
    reg = _load_registry()
    return load_strategy_from_registry(reg, strategy_key, env_var="FOX_STRATEGY")


def load_all_strategies(enabled_only=True):
    """Load all strategies from the registry."""
    reg = _load_registry()
    return load_all_from_registry(reg, enabled_only=enabled_only)


def state_dir(strategy_key):
    """Get (and create) the state directory for a strategy."""
    return make_state_dir(WORKSPACE, strategy_key)


def dsl_state_path(strategy_key, asset):
    """Get the DSL state file path for a strategy + asset."""
    return make_dsl_state_path(WORKSPACE, strategy_key, asset)


def dsl_state_glob(strategy_key):
    """Get the glob pattern for all DSL state files in a strategy."""
    return make_dsl_state_glob(WORKSPACE, strategy_key)


def get_all_active_positions():
    """Get all active positions across ALL strategies."""
    strategies = load_all_strategies()
    return get_all_active_positions_base(strategies, dsl_state_glob)


def heartbeat(cron_name):
    """Record that a cron job just ran."""
    heartbeat_write(HEARTBEAT_FILE, cron_name)


def send_notification(message):
    """Send a Telegram notification directly via mcporter."""
    try:
        reg = _load_registry()
        global_cfg = reg.get("global", {})
        chat_id = global_cfg.get("telegramChatId", "")
        send_notification_to_telegram(message, chat_id)
    except Exception:
        pass


@contextmanager
def strategy_lock(strategy_key, timeout=60):
    """Acquire an exclusive file lock per strategy key (FOX paths)."""
    lock_dir = os.path.join(WORKSPACE, "state", "locks")
    with _strategy_lock_base(lock_dir, strategy_key, timeout=timeout):
        yield


# ─── DSL state file validation (re-exported with FOX defaults) ──────────────

DSL_REQUIRED_KEYS = [
    "asset", "direction", "entryPrice", "size", "leverage",
    "highWaterPrice", "phase", "currentBreachCount",
    "currentTierIndex", "tierFloorPrice", "tiers", "phase1",
]

PHASE1_REQUIRED_KEYS = ["retraceThreshold", "consecutiveBreachesRequired"]


# ─── FOX-specific DSL state template (v5 format, 9-tier) ────────────────────

FOX_DEFAULT_TIERS = [
    {"triggerPct": 5, "lockPct": 2, "breaches": 2},
    {"triggerPct": 10, "lockPct": 5, "breaches": 2},
    {"triggerPct": 20, "lockPct": 14, "breaches": 2},
    {"triggerPct": 30, "lockPct": 24, "breaches": 2},
    {"triggerPct": 40, "lockPct": 34, "breaches": 1},
    {"triggerPct": 50, "lockPct": 44, "breaches": 1},
    {"triggerPct": 65, "lockPct": 56, "breaches": 1},
    {"triggerPct": 80, "lockPct": 72, "breaches": 1},
    {"triggerPct": 100, "lockPct": 90, "breaches": 1},
]

# Conviction-scaled Phase 1 timing
CONVICTION_TIERS = {
    "low":  {"retraceThreshold": 0.02, "hardTimeoutMin": 30, "weakPeakCutMin": 15, "deadWeightCutMin": 10},
    "mid":  {"retraceThreshold": 0.025, "hardTimeoutMin": 45, "weakPeakCutMin": 20, "deadWeightCutMin": 15},
    "high": {"retraceThreshold": 0.03, "hardTimeoutMin": 60, "weakPeakCutMin": 30, "deadWeightCutMin": 20},
}


def _get_conviction_tier(score):
    """Get Phase 1 timing parameters based on entry score."""
    if score is not None and score >= 10:
        return CONVICTION_TIERS["high"]
    elif score is not None and score >= 8:
        return CONVICTION_TIERS["mid"]
    else:
        return CONVICTION_TIERS["low"]


def dsl_state_template(asset, direction, entry_price, size, leverage,
                       strategy_key=None, strategy_id=None, wallet=None,
                       tiers=None, created_by="entry_flow",
                       score=None, is_reentry=False, reentry_of=None):
    """Create a FOX v5 DSL state dict for a new position.

    Uses FOX's 9-tier system, decimal retraceThreshold, and conviction-scaled
    Phase 1 timing fields.

    Args:
        asset: Coin symbol (e.g. "HYPE").
        direction: "LONG" or "SHORT".
        entry_price: Position entry price.
        size: Position size.
        leverage: Position leverage.
        strategy_key: Registry key (e.g. "fox-abc123").
        strategy_id: Strategy UUID.
        wallet: Strategy wallet address.
        tiers: Optional tier list. Uses FOX 9-tier defaults if None.
        created_by: Origin tag for audit.
        score: Entry score (6-10+) for conviction-scaled Phase 1.
        is_reentry: True if this is a re-entry trade.
        reentry_of: Original trade asset for re-entry tracking.

    Returns:
        A valid DSL state dict ready for atomic_write.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if tiers is None:
        tiers = [t.copy() for t in FOX_DEFAULT_TIERS]

    # Get conviction-scaled Phase 1 parameters
    conviction = _get_conviction_tier(score)
    retrace_threshold = conviction["retraceThreshold"]

    # Calculate absoluteFloor using FOX's decimal retraceThreshold
    retrace_price = retrace_threshold / leverage
    if direction.upper() == "LONG":
        abs_floor = round(entry_price * (1 - retrace_price), 6)
    else:
        abs_floor = round(entry_price * (1 + retrace_price), 6)

    return {
        "version": 3,
        "asset": asset,
        "direction": direction.upper(),
        "entryPrice": entry_price,
        "size": size,
        "leverage": leverage,
        "active": True,
        "highWaterPrice": entry_price,
        "phase": 1,
        "currentBreachCount": 0,
        "currentTierIndex": -1,
        "tierFloorPrice": 0,
        "floorPrice": abs_floor,
        "tiers": tiers,
        "phase1": {
            "retraceThreshold": retrace_threshold,
            "absoluteFloor": abs_floor,
            "consecutiveBreachesRequired": 3,
            "hardTimeoutMin": conviction["hardTimeoutMin"],
            "weakPeakCutMin": conviction["weakPeakCutMin"],
            "deadWeightCutMin": conviction["deadWeightCutMin"],
            "greenIn10TightenPct": 50,
        },
        "phase2": {
            "retraceThreshold": 0.015,
            "consecutiveBreachesRequired": 2,
        },
        "phase2TriggerTier": 0,
        "score": score,
        "isReentry": is_reentry,
        "reentryOf": reentry_of,
        "greenIn10": False,
        "wallet": wallet,
        "strategyId": strategy_id,
        "strategyKey": strategy_key,
        "createdAt": now,
        "updatedAt": now,
        "lastCheck": now,
        "createdBy": created_by,
    }
