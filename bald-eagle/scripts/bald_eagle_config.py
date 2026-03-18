# Copyright 2026 Senpi (https://senpi.ai)
# Licensed under MIT
# Source: https://github.com/Senpi-ai/senpi-skills

"""
BALD EAGLE v1.0 — Standalone Config Helper
===========================================
Self-contained utility module. No wolf_config dependency.

Provides: atomic_write, load_config, get_wallet_and_strategy,
load_state, save_state, load_trade_counter, save_trade_counter,
mcporter_call, get_positions, output.
"""

import json
import os
import sys
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

WORKSPACE = os.environ.get("WORKSPACE", "/data/workspace")
SKILL_NAME = "bald-eagle"
SKILL_DIR = os.path.join(WORKSPACE, "skills", SKILL_NAME)
STATE_DIR = os.path.join(SKILL_DIR, "state")
CONFIG_PATH = os.path.join(SKILL_DIR, "config", "skill-config.json")


def ensure_dirs():
    """Create state directory if it doesn't exist."""
    os.makedirs(STATE_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Atomic Write
# ---------------------------------------------------------------------------

def atomic_write(path: str, data: dict) -> None:
    """Write JSON via tmp file + atomic replace. Prevents partial writes."""
    ensure_dirs()
    dir_name = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Load skill-config.json. Returns empty dict on failure."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[BALD EAGLE] Config load error: {e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Wallet / Strategy
# ---------------------------------------------------------------------------

def get_wallet_and_strategy() -> tuple:
    """
    Get wallet address and strategy ID from env vars or config.
    Returns (wallet_address, strategy_id).
    """
    wallet = os.environ.get("WALLET_ADDRESS", "")
    strategy = os.environ.get("STRATEGY_ID", "")

    if not wallet or not strategy:
        cfg = load_config()
        wallet = wallet or cfg.get("wallet", {}).get("address", "")
        strategy = strategy or cfg.get("wallet", {}).get("strategyId", "")

    return wallet, strategy


# ---------------------------------------------------------------------------
# State I/O
# ---------------------------------------------------------------------------

def load_state(coin: str) -> dict | None:
    """Load DSL state for a specific coin. Returns None if not found."""
    path = os.path.join(STATE_DIR, f"dsl-{coin}.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_state(coin: str, state: dict) -> None:
    """Save DSL state for a specific coin via atomic write."""
    path = os.path.join(STATE_DIR, f"dsl-{coin}.json")
    atomic_write(path, state)


def clear_state(coin: str) -> None:
    """Remove DSL state file for a coin (after position close)."""
    path = os.path.join(STATE_DIR, f"dsl-{coin}.json")
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Trade Counter (daily gate)
# ---------------------------------------------------------------------------

def _counter_path() -> str:
    return os.path.join(STATE_DIR, "trade-counter.json")


def load_trade_counter() -> dict:
    """
    Load daily trade counter.
    Returns: {"date": "YYYY-MM-DD", "count": N, "assets": [...]}
    Resets if date doesn't match today.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = _counter_path()

    try:
        with open(path, "r") as f:
            data = json.load(f)
        if data.get("date") != today:
            data = {"date": today, "count": 0, "assets": []}
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"date": today, "count": 0, "assets": []}

    return data


def save_trade_counter(counter: dict) -> None:
    """Save trade counter via atomic write."""
    atomic_write(_counter_path(), counter)


def increment_trade(asset: str) -> dict:
    """Increment daily trade counter for an asset."""
    counter = load_trade_counter()
    counter["count"] += 1
    counter["assets"].append({
        "asset": asset,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    save_trade_counter(counter)
    return counter


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

def _cooldown_path() -> str:
    return os.path.join(STATE_DIR, "cooldowns.json")


def load_cooldowns() -> dict:
    """Load per-asset cooldown timestamps."""
    try:
        with open(_cooldown_path(), "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cooldowns(cooldowns: dict) -> None:
    """Save cooldown state."""
    atomic_write(_cooldown_path(), cooldowns)


def set_cooldown(asset: str, minutes: int = 120) -> None:
    """Set cooldown for an asset after a Phase 1 exit."""
    cooldowns = load_cooldowns()
    cooldowns[asset] = {
        "until": (datetime.now(timezone.utc).timestamp()) + (minutes * 60),
        "set_at": datetime.now(timezone.utc).isoformat(),
    }
    save_cooldowns(cooldowns)


def is_on_cooldown(asset: str) -> bool:
    """Check if an asset is still on cooldown."""
    cooldowns = load_cooldowns()
    entry = cooldowns.get(asset)
    if not entry:
        return False
    return time.time() < entry.get("until", 0)


# ---------------------------------------------------------------------------
# MCP Helper
# ---------------------------------------------------------------------------

def mcporter_call(tool_name: str, params: dict = None, retries: int = 2) -> dict:
    """
    Call a Senpi MCP tool with retry logic.

    In agent runtime, MCP calls are routed through the framework.
    This helper wraps the call with retries and error handling.
    """
    params = params or {}
    last_err = None

    for attempt in range(retries + 1):
        try:
            # The agent runtime provides the actual MCP client.
            # This function is monkey-patched at startup.
            # For standalone testing, falls back to REST API.
            result = _do_mcp_call(tool_name, params)
            if result is not None:
                return result
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1 * (attempt + 1))
                continue

    print(f"[BALD EAGLE] MCP call {tool_name} failed after {retries + 1} attempts: {last_err}",
          file=sys.stderr)
    return {}


def _do_mcp_call(tool_name: str, params: dict) -> dict:
    """
    Execute MCP tool call. Replaced at runtime by agent framework.
    Fallback: attempt REST API call.
    """
    api_base = os.environ.get("SENPI_API_BASE", "")
    if api_base:
        try:
            import requests
            resp = requests.post(
                f"{api_base}/mcp/{tool_name}",
                json=params,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise RuntimeError(f"REST fallback failed: {e}")

    # No API base and no runtime injection — return empty
    return {}


# ---------------------------------------------------------------------------
# Position Helper
# ---------------------------------------------------------------------------

def get_positions(wallet: str = None) -> list:
    """
    Get current open positions from clearinghouse state.
    Returns list of position dicts.
    """
    if not wallet:
        wallet, _ = get_wallet_and_strategy()

    result = mcporter_call("strategy_get_clearinghouse_state", {"wallet": wallet})

    # isinstance() guard — Senpi returns vary
    if isinstance(result, dict):
        perp_state = result.get("assetPositions", result.get("positions", []))
    elif isinstance(result, list):
        perp_state = result
    else:
        perp_state = []

    positions = []
    for item in perp_state:
        if isinstance(item, dict):
            pos = item.get("position", item)
            coin = pos.get("coin", pos.get("asset", ""))
            szi = float(pos.get("szi", pos.get("size", 0)))
            if szi != 0:
                positions.append(pos)

    return positions


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def output(data: dict) -> None:
    """Print JSON to stdout for agent consumption."""
    print(json.dumps(data, indent=2, default=str))
