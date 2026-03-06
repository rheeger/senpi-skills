#!/usr/bin/env python3
"""
wolf_config.py — Multi-strategy config loader for WOLF v6.1.1

Provides a single importable module every script uses to load strategy config,
resolve state file paths, and handle legacy migration.

Usage:
    from wolf_config import load_strategy, load_all_strategies, dsl_state_path
    cfg = load_strategy("wolf-abc123")   # Specific strategy
    cfg = load_strategy()                # Default strategy
    strategies = load_all_strategies()   # All enabled strategies
    path = dsl_state_path("wolf-abc123", "HYPE")
"""

import glob
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

# ─── Import shared utilities from senpi_lib ──────────────────────────────────
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
SKILLS_ROOT = os.path.dirname(SKILL_DIR)
sys.path.insert(0, os.path.join(SKILLS_ROOT, "shared"))

from senpi_lib import (RISK_LEVERAGE_RANGES, ROTATION_COOLDOWN_MINUTES,
                       SIGNAL_CONVICTION, atomic_write, calculate_leverage,
                       count_active_dsls, extract_positions_from_section,
                       extract_single_position, fail_json,
                       get_all_active_positions_base, get_wallet_positions,
                       heartbeat_write, load_all_from_registry,
                       load_strategy_from_registry, load_strategy_registry,
                       make_dsl_state_glob, make_dsl_state_path,
                       make_state_dir, mcporter_call, mcporter_call_safe,
                       send_notification_to_telegram)
from senpi_lib import strategy_lock as _strategy_lock_base
from senpi_lib import validate_dsl_state

# ─── WOLF-specific paths ─────────────────────────────────────────────────────

WORKSPACE = os.environ.get("WOLF_WORKSPACE",
    os.environ.get("OPENCLAW_WORKSPACE", "/data/workspace"))
REGISTRY_FILE = os.path.join(WORKSPACE, "wolf-strategies.json")
LEGACY_CONFIG = os.path.join(WORKSPACE, "wolf-strategy.json")
LEGACY_STATE_PATTERN = os.path.join(WORKSPACE, "dsl-state-WOLF-*.json")
HEARTBEAT_FILE = os.path.join(WORKSPACE, "state", "cron-heartbeats.json")

_fail = fail_json


def _migrate_legacy_state_files(strategy_key):
    """Move old dsl-state-WOLF-*.json files into state/{strategy_key}/dsl-*.json."""
    legacy_files = glob.glob(LEGACY_STATE_PATTERN)
    if not legacy_files:
        return

    new_dir = os.path.join(WORKSPACE, "state", strategy_key)
    os.makedirs(new_dir, exist_ok=True)

    for old_path in legacy_files:
        basename = os.path.basename(old_path)
        asset = basename.replace("dsl-state-WOLF-", "").replace(".json", "")
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

    with open(LEGACY_CONFIG) as f:
        legacy = json.load(f)
    sid = legacy.get("strategyId", "unknown")
    key = f"wolf-{sid[:8]}" if sid != "unknown" else "wolf-default"

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
            "tiers": [
                {"triggerPct": 5, "lockPct": 50, "breaches": 3},
                {"triggerPct": 10, "lockPct": 65, "breaches": 2},
                {"triggerPct": 15, "lockPct": 75, "breaches": 2},
                {"triggerPct": 20, "lockPct": 85, "breaches": 1}
            ]
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


# ─── Thin wrappers that inject WOLF paths ─────────────────────────────────────

def load_strategy(strategy_key=None):
    """Load a single strategy config."""
    reg = _load_registry()
    return load_strategy_from_registry(reg, strategy_key, env_var="WOLF_STRATEGY")


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
    """Acquire an exclusive file lock per strategy key (WOLF paths)."""
    lock_dir = os.path.join(WORKSPACE, "state", "locks")
    with _strategy_lock_base(lock_dir, strategy_key, timeout=timeout):
        yield


# ─── DSL state file validation (re-exported with WOLF defaults) ──────────────

DSL_REQUIRED_KEYS = [
    "asset", "direction", "entryPrice", "size", "leverage",
    "highWaterPrice", "phase", "currentBreachCount",
    "currentTierIndex", "tierFloorPrice", "tiers", "phase1",
]

PHASE1_REQUIRED_KEYS = ["retraceThreshold", "consecutiveBreachesRequired"]


# ─── WOLF-specific DSL state template ────────────────────────────────────────

def dsl_state_template(asset, direction, entry_price, size, leverage,
                       strategy_key=None, tiers=None, created_by="entry_flow"):
    """Create a minimal valid DSL state dict for a new position.

    Args:
        asset: Coin symbol (e.g. "HYPE").
        direction: "LONG" or "SHORT".
        entry_price: Position entry price.
        size: Position size.
        leverage: Position leverage.
        strategy_key: Optional strategy key to embed.
        tiers: Optional tier list. Uses aggressive defaults if None.
        created_by: Origin tag for audit.

    Returns:
        A valid DSL state dict ready for atomic_write.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if tiers is None:
        tiers = [
            {"triggerPct": 5, "lockPct": 50, "breaches": 3},
            {"triggerPct": 10, "lockPct": 65, "breaches": 2},
            {"triggerPct": 15, "lockPct": 75, "breaches": 2},
            {"triggerPct": 20, "lockPct": 85, "breaches": 1},
        ]

    retrace_roe = 10
    retrace_price = (retrace_roe / 100) / leverage
    if direction.upper() == "LONG":
        abs_floor = round(entry_price * (1 - retrace_price), 6)
    else:
        abs_floor = round(entry_price * (1 + retrace_price), 6)

    return {
        "version": 2,
        "asset": asset,
        "direction": direction.upper(),
        "entryPrice": entry_price,
        "size": size,
        "leverage": leverage,
        "active": True,
        "highWaterPrice": entry_price,
        "phase": 1,
        "currentBreachCount": 0,
        "currentTierIndex": None,
        "tierFloorPrice": 0,
        "floorPrice": abs_floor,
        "tiers": tiers,
        "phase1": {
            "retraceThreshold": 10,
            "absoluteFloor": abs_floor,
            "consecutiveBreachesRequired": 3,
        },
        "phase2TriggerTier": 0,
        "createdAt": now,
        "lastCheck": now,
        "strategyKey": strategy_key,
        "createdBy": created_by,
    }


# ─── Guard Rail defaults & helpers (WOLF v6.1.1) ────────────────────────────

GUARD_RAIL_DEFAULTS = {
    "maxEntriesPerDay": 8,
    "bypassOnProfit": True,
    "maxConsecutiveLosses": 3,
    "cooldownMinutes": 60,
}


def trade_counter_path(strategy_key):
    """Return the path to the trade counter file for a strategy."""
    return os.path.join(state_dir(strategy_key), "trade-counter.json")


def load_trade_counter(strategy_key):
    """Load (or create) the daily trade counter for a strategy.

    Handles day rollover: resets daily counters but preserves streaks,
    active cooldowns, and processedOrderIds.
    """
    path = trade_counter_path(strategy_key)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    old = {}
    try:
        with open(path) as f:
            old = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    try:
        cfg = load_strategy(strategy_key)
        gr_cfg = cfg.get("guardRails", {})
    except (SystemExit, Exception):
        gr_cfg = {}

    merged_config = {k: gr_cfg.get(k, v) for k, v in GUARD_RAIL_DEFAULTS.items()}

    if old.get("date") == today:
        old.update(merged_config)
        return old

    counter = {
        "date": today,
        "accountValueStart": None,
        "entries": 0,
        "closedTrades": 0,
        "realizedPnl": 0.0,
        "gate": "OPEN",
        "gateReason": None,
        "cooldownUntil": None,
        "lastResults": old.get("lastResults", []),
        "processedOrderIds": [],
        "updatedAt": None,
    }
    counter.update(merged_config)

    cooldown_until = old.get("cooldownUntil")
    if cooldown_until:
        try:
            cd_dt = datetime.fromisoformat(cooldown_until.replace("Z", "+00:00"))
            if cd_dt > datetime.now(timezone.utc):
                counter["gate"] = "COOLDOWN"
                counter["gateReason"] = "consecutive_losses_cooldown (carried from previous day)"
                counter["cooldownUntil"] = cooldown_until
        except (ValueError, TypeError):
            pass

    return counter


def save_trade_counter(strategy_key, counter):
    """Save the trade counter, stamping updatedAt."""
    counter["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    atomic_write(trade_counter_path(strategy_key), counter)


def check_gate(strategy_key):
    """Lightweight gate check. Returns (gate_status, gate_reason)."""
    path = trade_counter_path(strategy_key)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        with open(path) as f:
            counter = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return ("OPEN", None)

    if counter.get("date") != today:
        cooldown_until = counter.get("cooldownUntil")
        if cooldown_until:
            try:
                cd_dt = datetime.fromisoformat(cooldown_until.replace("Z", "+00:00"))
                if cd_dt > datetime.now(timezone.utc):
                    return ("COOLDOWN", counter.get("gateReason", "consecutive_losses_cooldown"))
            except (ValueError, TypeError):
                pass
        return ("OPEN", None)

    gate = counter.get("gate", "OPEN")

    if gate == "CLOSED":
        return ("CLOSED", counter.get("gateReason"))

    if gate == "COOLDOWN":
        cooldown_until = counter.get("cooldownUntil")
        if cooldown_until:
            try:
                cd_dt = datetime.fromisoformat(cooldown_until.replace("Z", "+00:00"))
                if cd_dt > datetime.now(timezone.utc):
                    return ("COOLDOWN", counter.get("gateReason"))
            except (ValueError, TypeError):
                pass
        with strategy_lock(strategy_key):
            counter = load_trade_counter(strategy_key)
            if counter.get("gate") != "COOLDOWN":
                return (counter.get("gate", "OPEN"), counter.get("gateReason"))
            counter["gate"] = "OPEN"
            counter["gateReason"] = None
            counter["cooldownUntil"] = None
            results = counter.get("lastResults", [])
            results.append("R")
            counter["lastResults"] = results[-20:]
            save_trade_counter(strategy_key, counter)
        return ("OPEN", None)

    return ("OPEN", None)


def increment_entry_counter(strategy_key):
    """Load counter, increment entries, save. Returns updated counter."""
    counter = load_trade_counter(strategy_key)
    counter["entries"] = counter.get("entries", 0) + 1
    save_trade_counter(strategy_key, counter)
    return counter
