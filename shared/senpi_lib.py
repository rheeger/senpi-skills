#!/usr/bin/env python3
"""
senpi_lib.py — Shared utility library for Senpi trading skills (WOLF, FOX, etc.)

Eliminates duplication across skill configs. Each skill's *_config.py imports
from here and adds skill-specific logic (workspace paths, DSL templates, etc.).

Usage:
    # In fox_config.py or wolf_config.py:
    SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
    SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
    SKILLS_ROOT = os.path.dirname(SKILL_DIR)
    sys.path.insert(0, os.path.join(SKILLS_ROOT, "shared"))
    from senpi_lib import mcporter_call, atomic_write, ...
"""

import fcntl
import glob
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone

# ─── MCP / External Calls ────────────────────────────────────────────────────

_mcporter_bin_cache = None

def _resolve_mcporter():
    """Resolve mcporter binary, preferring the gate wrapper for auth injection.

    Priority: MCPORTER_CMD env var > auto-discovered wrapper > bare mcporter.
    The gate wrapper routes senpi calls through mcporter-gate/handler.py which
    injects the auth token from the passkey gate vault.
    """
    global _mcporter_bin_cache
    if _mcporter_bin_cache is not None:
        return _mcporter_bin_cache
    explicit = os.environ.get("MCPORTER_CMD")
    if explicit:
        _mcporter_bin_cache = explicit
        return explicit
    here = os.path.dirname(os.path.abspath(__file__))
    wrapper = os.path.normpath(os.path.join(
        here, "..", "..", "runtime", "bin", "mcporter-senpi-wrapper.sh"))
    if os.path.isfile(wrapper):
        _mcporter_bin_cache = wrapper
        return wrapper
    _mcporter_bin_cache = "mcporter"
    return "mcporter"


def mcporter_call(tool, retries=3, timeout=30, **kwargs):
    """Call a Senpi MCP tool via mcporter using --args JSON blob.

    Args:
        tool: Tool name (e.g. "market_get_prices", "close_position").
        retries: Number of attempts before giving up.
        timeout: Subprocess timeout in seconds.
        **kwargs: Tool arguments passed as a single --args JSON blob.

    Returns:
        The `data` dict from the MCP response envelope.

    Raises:
        RuntimeError: If all retries fail or the tool returns success=false.
    """
    filtered_args = {k: v for k, v in kwargs.items() if v is not None}

    mcporter_bin = _resolve_mcporter()
    cmd = [mcporter_bin, "call", f"senpi.{tool}"]
    if filtered_args:
        cmd.extend(["--args", json.dumps(filtered_args)])
    cmd_str = " ".join(shlex.quote(c) for c in cmd)
    last_error = None

    for attempt in range(retries):
        fd, tmp = None, None
        try:
            fd, tmp = tempfile.mkstemp(suffix=".json")
            os.close(fd)
            subprocess.run(
                f"{cmd_str} > {tmp} 2>/dev/null",
                shell=True, timeout=timeout,
            )
            with open(tmp) as f:
                d = json.load(f)
            if d.get("success"):
                return d.get("data", {})
            last_error = d.get("error", d)
        except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError) as e:
            last_error = str(e)
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
        if attempt < retries - 1:
            time.sleep(3)

    raise RuntimeError(f"mcporter {tool} failed after {retries} attempts: {last_error}")


def mcporter_call_safe(tool, retries=3, timeout=30, **kwargs):
    """Like mcporter_call but returns None instead of raising on failure."""
    try:
        return mcporter_call(tool, retries=retries, timeout=timeout, **kwargs)
    except RuntimeError:
        return None


# ─── File Management ─────────────────────────────────────────────────────────

def atomic_write(path, data):
    """Atomically write JSON data to a file.

    Handles pre-serialized strings (recovers via json.loads).
    """
    if isinstance(data, str):
        data = json.loads(data)  # recover from pre-serialized input
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def fail_json(msg):
    """Print error JSON and exit."""
    print(json.dumps({"success": False, "error": msg}))
    sys.exit(1)


# ─── Locking ─────────────────────────────────────────────────────────────────

@contextmanager
def strategy_lock(lock_dir, strategy_key, timeout=60):
    """Acquire an exclusive file lock per strategy key.

    Serializes position opens so that concurrent calls cannot race past
    the slot check.

    Args:
        lock_dir: Directory for lock files (e.g. WORKSPACE/state/locks).
        strategy_key: Strategy key (e.g. "wolf-abc123").
        timeout: Seconds to wait for lock before raising.

    Yields once the lock is held; releases on exit.
    """
    os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.join(lock_dir, f"{strategy_key}.lock")
    fd = open(lock_path, "w")
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (IOError, OSError):
                if time.monotonic() >= deadline:
                    fd.close()
                    raise RuntimeError(f"Could not acquire lock for {strategy_key} within {timeout}s")
                time.sleep(0.2)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            fd.close()


# ─── Health & Monitoring ─────────────────────────────────────────────────────

def heartbeat_write(heartbeat_file, cron_name):
    """Record that a cron job just ran. Called at the start of each script."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with open(heartbeat_file) as f:
            beats = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        beats = {}
    beats[cron_name] = now
    atomic_write(heartbeat_file, beats)


def send_notification_to_telegram(message, chat_id, mcporter_fn=None):
    """Send a Telegram notification via mcporter.

    Silently fails — notifications should never crash the calling script.

    Args:
        message: Text to send.
        chat_id: Telegram chat ID.
        mcporter_fn: Optional mcporter_call_safe function override.
    """
    if mcporter_fn is None:
        mcporter_fn = mcporter_call_safe
    try:
        if not chat_id:
            return
        target = f"telegram:{chat_id}"
        mcporter_fn("send_telegram_notification", retries=2, timeout=10,
                     target=target, message=message)
    except Exception:
        pass  # never crash the caller


# ─── Trading Utilities ───────────────────────────────────────────────────────

RISK_LEVERAGE_RANGES = {
    "conservative": (0.15, 0.25),   # 15%-25% of max leverage
    "moderate":     (0.25, 0.50),   # 25%-50% of max leverage
    "aggressive":   (0.50, 0.75),   # 50%-75% of max leverage
}

SIGNAL_CONVICTION = {
    "FIRST_JUMP": 0.9,
    "CONTRIB_EXPLOSION": 0.8,
    "IMMEDIATE_MOVER": 0.7,
    "NEW_ENTRY_DEEP": 0.7,
    "DEEP_CLIMBER": 0.5,
}

ROTATION_COOLDOWN_MINUTES = 45  # positions younger than this can't be rotated out


def calculate_leverage(max_leverage, trading_risk="moderate", conviction=0.5):
    """Calculate leverage as a fraction of max leverage, scaled by risk tier and conviction.

    Args:
        max_leverage: Asset's maximum allowed leverage.
        trading_risk: Risk tier — "conservative", "moderate", or "aggressive".
        conviction: 0.0 to 1.0, where within the risk range to land.

    Returns:
        Integer leverage, clamped to [1, max_leverage].
    """
    min_pct, max_pct = RISK_LEVERAGE_RANGES.get(trading_risk, RISK_LEVERAGE_RANGES["moderate"])
    range_min = max_leverage * min_pct
    range_max = max_leverage * max_pct
    leverage = range_min + (range_max - range_min) * conviction
    return min(max(1, round(leverage)), max_leverage)


# ─── DSL Validation ──────────────────────────────────────────────────────────

def validate_dsl_state(state, state_file=None, required_keys=None, phase1_required_keys=None):
    """Validate a DSL state dict has all required keys.

    Args:
        state: The parsed JSON state dict.
        state_file: Optional file path for error messages.
        required_keys: Override for top-level required keys.
        phase1_required_keys: Override for phase1 required keys.

    Returns:
        (True, None) if valid, (False, error_message) if invalid.
    """
    if required_keys is None:
        required_keys = [
            "asset", "direction", "entryPrice", "size", "leverage",
            "highWaterPrice", "phase", "currentBreachCount",
            "currentTierIndex", "tierFloorPrice", "tiers", "phase1",
        ]
    if phase1_required_keys is None:
        phase1_required_keys = ["retraceThreshold", "consecutiveBreachesRequired"]

    if not isinstance(state, dict):
        return False, f"state is not a dict ({state_file or 'unknown'})"

    missing = [k for k in required_keys if k not in state]
    if missing:
        return False, f"missing keys {missing} ({state_file or 'unknown'})"

    phase1 = state.get("phase1")
    if not isinstance(phase1, dict):
        return False, f"phase1 is not a dict ({state_file or 'unknown'})"

    missing_p1 = [k for k in phase1_required_keys if k not in phase1]
    if missing_p1:
        return False, f"phase1 missing keys {missing_p1} ({state_file or 'unknown'})"

    if not isinstance(state.get("tiers"), list):
        return False, f"tiers is not a list ({state_file or 'unknown'})"

    return True, None


# ─── Clearinghouse Data Extraction ───────────────────────────────────────────

def extract_positions_from_section(section_data):
    """Extract non-zero positions from a clearinghouse section.

    Args:
        section_data: Dict from clearinghouse response (e.g. data["main"]).

    Returns:
        Dict of coin → position info.
    """
    if not isinstance(section_data, dict):
        return {}
    positions = {}
    for p in section_data.get("assetPositions", []):
        if not isinstance(p, dict):
            continue
        pos = p.get("position", {})
        coin = pos.get("coin")
        if not coin:
            continue
        szi = float(pos.get("szi", 0))
        if szi == 0:
            continue
        margin_used = float(pos.get("marginUsed", 0))
        pos_value = float(pos.get("positionValue", 0))
        positions[coin] = {
            "direction": "SHORT" if szi < 0 else "LONG",
            "size": abs(szi),
            "entryPx": pos.get("entryPx"),
            "unrealizedPnl": pos.get("unrealizedPnl"),
            "returnOnEquity": pos.get("returnOnEquity"),
            "leverage": round(pos_value / margin_used, 1) if margin_used > 0 else None,
            "marginUsed": margin_used,
            "positionValue": pos_value,
        }
    return positions


def get_wallet_positions(wallet, mcporter_fn=None):
    """Get all positions (crypto + xyz) from a single clearinghouse call.

    Args:
        wallet: Strategy wallet address.
        mcporter_fn: Optional mcporter_call_safe function override.

    Returns:
        (crypto_positions, xyz_positions, error_string_or_None).
    """
    if mcporter_fn is None:
        mcporter_fn = mcporter_call_safe
    data = mcporter_fn("strategy_get_clearinghouse_state", strategy_wallet=wallet)
    if not data:
        return {}, {}, "clearinghouse fetch failed"
    crypto = extract_positions_from_section(data.get("main", {}))
    xyz = extract_positions_from_section(data.get("xyz", {}))
    return crypto, xyz, None


def extract_single_position(clearinghouse_data, coin, dex=None):
    """Extract a specific position from clearinghouse data.

    Args:
        clearinghouse_data: Full clearinghouse response.
        coin: Coin name (e.g. "HYPE", "xyz:AAPL").
        dex: Optional dex hint ("xyz" or None).

    Returns:
        Position dict or None.
    """
    section_key = "xyz" if dex == "xyz" else "main"
    section = clearinghouse_data.get(section_key, {})
    for p in section.get("assetPositions", []):
        if not isinstance(p, dict):
            continue
        pos = p.get("position", {})
        if pos.get("coin") == coin:
            szi = float(pos.get("szi", 0))
            if szi == 0:
                continue
            margin_used = float(pos.get("marginUsed", 0))
            pos_value = float(pos.get("positionValue", 0))
            return {
                "entryPx": float(pos.get("entryPx", 0)),
                "size": abs(szi),
                "leverage": round(pos_value / margin_used, 1) if margin_used > 0 else None,
                "direction": "SHORT" if szi < 0 else "LONG",
            }
    return None


def count_active_dsls(glob_pattern, approx_grace_minutes=10):
    """Count active DSL state files, excluding stale approximate DSLs.

    Args:
        glob_pattern: Glob pattern for DSL state files.
        approx_grace_minutes: Approximate DSLs older than this don't count.

    Returns:
        Integer count of active DSLs.
    """
    now = datetime.now(timezone.utc)
    count = 0
    for sf in glob.glob(glob_pattern):
        try:
            with open(sf) as f:
                state = json.load(f)
            if not state.get("active"):
                continue
            # Skip stale approximate DSLs from slot count
            if state.get("approximate") and state.get("createdAt"):
                try:
                    created = datetime.fromisoformat(state["createdAt"].replace("Z", "+00:00"))
                    age_min = (now - created).total_seconds() / 60
                    if age_min > approx_grace_minutes:
                        continue
                except (ValueError, TypeError):
                    pass
            count += 1
        except (json.JSONDecodeError, IOError, AttributeError):
            continue
    return count


# ─── Config Base (Strategy Registry) ─────────────────────────────────────────

def load_strategy_registry(registry_file, legacy_config=None, retry=True):
    """Load a strategy registry file with optional retry and legacy fallback.

    Args:
        registry_file: Path to the registry JSON file.
        legacy_config: Path to legacy single-strategy config (for migration).
        retry: If True, retry once on file-not-found (transient filesystem).

    Returns:
        Parsed registry dict.
    """
    attempts = 2 if retry else 1
    for attempt in range(attempts):
        if os.path.exists(registry_file):
            try:
                with open(registry_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                if attempt == 0 and retry:
                    time.sleep(1)
                    continue
                fail_json(f"Registry file corrupt at {registry_file}: {e}")
        elif attempt == 0 and retry:
            time.sleep(1)
            continue
        else:
            break

    # Legacy fallback handled by caller (skill-specific migration logic)
    if legacy_config and os.path.exists(legacy_config):
        return None  # signal caller to handle migration
    fail_json(f"No config found at {registry_file}. Run setup first.")


def load_strategy_from_registry(registry, strategy_key, env_var=None):
    """Look up a strategy in the registry and inject metadata.

    Args:
        registry: Parsed registry dict.
        strategy_key: Key to look up (e.g. "fox-abc123").
        env_var: Env var to check if strategy_key is None (e.g. "FOX_STRATEGY").

    Returns:
        Strategy config dict with _key, _global, _workspace, _state_dir.
    """
    workspace = registry.get("global", {}).get("workspace", "/data/workspace")
    if strategy_key is None and env_var:
        strategy_key = os.environ.get(env_var, registry.get("defaultStrategy"))
    if strategy_key is None:
        strategy_key = registry.get("defaultStrategy")
    if not strategy_key or strategy_key not in registry.get("strategies", {}):
        fail_json(f"Strategy '{strategy_key}' not found. "
                  f"Available: {list(registry.get('strategies', {}).keys())}")
    cfg = registry["strategies"][strategy_key].copy()
    cfg["_key"] = strategy_key
    cfg["_global"] = registry.get("global", {})
    cfg["_workspace"] = workspace
    cfg["_state_dir"] = os.path.join(workspace, "state", strategy_key)
    return cfg


def load_all_from_registry(registry, enabled_only=True):
    """Iterate all strategies in a registry and inject metadata.

    Args:
        registry: Parsed registry dict.
        enabled_only: If True (default), skip disabled strategies.

    Returns:
        Dict of strategy_key → strategy config.
    """
    workspace = registry.get("global", {}).get("workspace", "/data/workspace")
    result = {}
    for key, cfg in registry.get("strategies", {}).items():
        if enabled_only and not cfg.get("enabled", True):
            continue
        entry = cfg.copy()
        entry["_key"] = key
        entry["_global"] = registry.get("global", {})
        entry["_workspace"] = workspace
        entry["_state_dir"] = os.path.join(workspace, "state", key)
        result[key] = entry
    return result


def make_state_dir(workspace, strategy_key):
    """Get (and create) the state directory for a strategy."""
    d = os.path.join(workspace, "state", strategy_key)
    os.makedirs(d, exist_ok=True)
    return d


def make_dsl_state_path(workspace, strategy_key, asset):
    """Get the DSL state file path for a strategy + asset."""
    return os.path.join(make_state_dir(workspace, strategy_key), f"dsl-{asset}.json")


def make_dsl_state_glob(workspace, strategy_key):
    """Get the glob pattern for all DSL state files in a strategy."""
    return os.path.join(make_state_dir(workspace, strategy_key), "dsl-*.json")


def get_all_active_positions_base(strategies, dsl_state_glob_fn):
    """Get all active positions across strategies by scanning DSL state files.

    Args:
        strategies: Dict of strategy_key → config (from load_all_from_registry).
        dsl_state_glob_fn: Function(strategy_key) → glob pattern string.

    Returns:
        Dict of asset → list of {strategyKey, direction, stateFile}.
    """
    positions = {}
    for key in strategies:
        for sf in glob.glob(dsl_state_glob_fn(key)):
            try:
                with open(sf) as f:
                    s = json.load(f)
                if s.get("active"):
                    asset = s["asset"]
                    if asset not in positions:
                        positions[asset] = []
                    positions[asset].append({
                        "strategyKey": key,
                        "direction": s["direction"],
                        "stateFile": sf
                    })
            except (json.JSONDecodeError, IOError, KeyError, AttributeError):
                continue
    return positions
