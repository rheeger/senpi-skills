# Copyright 2026 Senpi (https://senpi.ai)
# Licensed under MIT
# Source: https://github.com/Senpi-ai/senpi-skills

"""
HYDRA v1.0 — Standalone Config Helper
======================================
Self-contained utility module. No wolf_config dependency.

v1.0.1 fixes:
- mcporter_call uses subprocess CLI (matches all other skills)
- get_positions unwraps main/xyz nesting correctly
- get_wallet_balance unwraps marginSummary correctly
"""

import json
import os
import subprocess
import sys
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

WORKSPACE = os.environ.get("OPENCLAW_WORKSPACE", os.environ.get("WORKSPACE", "/data/workspace"))
SKILL_NAME = "hydra"
SKILL_DIR = os.path.join(WORKSPACE, "skills", SKILL_NAME)
STATE_DIR = os.path.join(SKILL_DIR, "state")
OI_HISTORY_DIR = os.path.join(STATE_DIR, "oi-history")
CONFIG_PATH = os.path.join(SKILL_DIR, "config", "hydra-config.json")


def ensure_dirs():
    """Create state and OI history directories if they don't exist."""
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(OI_HISTORY_DIR, exist_ok=True)


ensure_dirs()


# ---------------------------------------------------------------------------
# Atomic Write
# ---------------------------------------------------------------------------

def atomic_write(path: str, data) -> None:
    """Write JSON via tmp file + atomic replace."""
    dir_name = os.path.dirname(path)
    os.makedirs(dir_name, exist_ok=True)
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
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log(f"Config load error: {e}")
        return {}


# ---------------------------------------------------------------------------
# Wallet / Strategy
# ---------------------------------------------------------------------------

def get_wallet_and_strategy() -> tuple:
    wallet = os.environ.get("HYDRA_WALLET", os.environ.get("WALLET_ADDRESS", ""))
    strategy = os.environ.get("HYDRA_STRATEGY_ID", os.environ.get("STRATEGY_ID", ""))
    if not wallet or not strategy:
        cfg = load_config()
        wallet = wallet or cfg.get("wallet", {}).get("address", cfg.get("wallet", ""))
        strategy = strategy or cfg.get("wallet", {}).get("strategyId", cfg.get("strategyId", ""))
    return wallet, strategy


# ---------------------------------------------------------------------------
# DSL State I/O
# ---------------------------------------------------------------------------

def load_state(coin: str) -> dict | None:
    path = os.path.join(STATE_DIR, f"dsl-{coin}.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_state(coin: str, state: dict) -> None:
    path = os.path.join(STATE_DIR, f"dsl-{coin}.json")
    atomic_write(path, state)


def clear_state(coin: str) -> None:
    path = os.path.join(STATE_DIR, f"dsl-{coin}.json")
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def list_active_dsl_states() -> list:
    """List all active DSL state files. Returns list of (coin, state) tuples."""
    active = []
    for f in os.listdir(STATE_DIR):
        if f.startswith("dsl-") and f.endswith(".json"):
            coin = f[4:-5]
            state = load_state(coin)
            if state and state.get("active"):
                active.append((coin, state))
    return active


# ---------------------------------------------------------------------------
# Runtime State
# ---------------------------------------------------------------------------

def _runtime_path() -> str:
    return os.path.join(STATE_DIR, "runtime.json")


def load_runtime() -> dict:
    path = _runtime_path()
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "entriesThisDay": 0,
            "entriesDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "gate": "OPEN",
            "gateExpiresAt": None,
            "consecutiveLosses": 0,
            "tradeLog": [],
            "tierStats": {
                "MEDIUM": {"trades": 0, "wins": 0, "losses": 0},
                "HIGH": {"trades": 0, "wins": 0, "losses": 0},
            },
        }


def save_runtime(runtime: dict) -> None:
    atomic_write(_runtime_path(), runtime)


def record_trade(runtime: dict, asset: str, tier: str, score: int,
                 outcome: str, roe: float) -> dict:
    runtime["tradeLog"].append({
        "asset": asset, "tier": tier, "score": score,
        "outcome": outcome, "roe": roe,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    if tier not in runtime["tierStats"]:
        runtime["tierStats"][tier] = {"trades": 0, "wins": 0, "losses": 0}
    runtime["tierStats"][tier]["trades"] += 1
    if roe > 0:
        runtime["tierStats"][tier]["wins"] += 1
        runtime["consecutiveLosses"] = 0
    else:
        runtime["tierStats"][tier]["losses"] += 1
        runtime["consecutiveLosses"] += 1
    return runtime


def check_gate(runtime: dict, config: dict) -> tuple:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if runtime.get("entriesDate") != today:
        runtime["entriesThisDay"] = 0
        runtime["entriesDate"] = today
        if runtime["gate"] == "CLOSED":
            runtime["gate"] = "OPEN"

    gate_cfg = config.get("gate", {})
    max_entries = gate_cfg.get("maxEntriesPerDay", 6)
    if runtime["entriesThisDay"] >= max_entries:
        runtime["gate"] = "CLOSED"
        return False, f"Daily limit reached ({runtime['entriesThisDay']}/{max_entries})"

    if runtime["gate"] == "COOLDOWN":
        expires = runtime.get("gateExpiresAt")
        if expires and time.time() < expires:
            return False, f"Cooldown active until {datetime.fromtimestamp(expires, tz=timezone.utc).isoformat()}"
        runtime["gate"] = "OPEN"
        runtime["gateExpiresAt"] = None

    max_losses = gate_cfg.get("maxConsecutiveLosses", 3)
    if runtime["consecutiveLosses"] >= max_losses:
        cooldown_min = gate_cfg.get("cooldownMinutes", 30)
        runtime["gate"] = "COOLDOWN"
        runtime["gateExpiresAt"] = time.time() + (cooldown_min * 60)
        return False, f"{runtime['consecutiveLosses']} consecutive losses → cooldown {cooldown_min}min"

    return True, "OPEN"


def is_tier_enabled(tier: str, runtime: dict, config: dict) -> bool:
    tier_cfg = config.get("convictionTiers", {}).get(tier, {})
    if tier_cfg.get("enabled") is False:
        return False
    learning_cfg = config.get("learning", {})
    if not learning_cfg.get("enabled", True):
        return True
    stats = runtime.get("tierStats", {}).get(tier, {})
    trades = stats.get("trades", 0)
    min_trades = learning_cfg.get("minTradesForDisable", 8)
    min_wr = learning_cfg.get("minWinRateForEnable", 0.15)
    if trades >= min_trades:
        wins = stats.get("wins", 0)
        wr = wins / trades if trades > 0 else 0
        if wr < min_wr:
            return False
    return True


# ---------------------------------------------------------------------------
# Cooldowns
# ---------------------------------------------------------------------------

def _cooldown_path() -> str:
    return os.path.join(STATE_DIR, "asset-cooldowns.json")


def load_cooldowns() -> dict:
    try:
        with open(_cooldown_path(), "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cooldowns(cooldowns: dict) -> None:
    atomic_write(_cooldown_path(), cooldowns)


def set_cooldown(asset: str, minutes: int = 120) -> None:
    cooldowns = load_cooldowns()
    cooldowns[asset] = {
        "until": time.time() + (minutes * 60),
        "set_at": datetime.now(timezone.utc).isoformat(),
    }
    save_cooldowns(cooldowns)


def is_on_cooldown(asset: str) -> bool:
    cooldowns = load_cooldowns()
    entry = cooldowns.get(asset)
    if not entry:
        return False
    return time.time() < entry.get("until", 0)


# ---------------------------------------------------------------------------
# OI History
# ---------------------------------------------------------------------------

def load_oi_history(asset: str) -> list:
    path = os.path.join(OI_HISTORY_DIR, f"{asset}.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def append_oi_snapshot(asset: str, oi_value: float) -> None:
    history = load_oi_history(asset)
    now = time.time()
    history.append({"oi": oi_value, "ts": now})
    cutoff = now - (7 * 24 * 3600)
    history = [h for h in history if h["ts"] > cutoff]
    path = os.path.join(OI_HISTORY_DIR, f"{asset}.json")
    atomic_write(path, history)


def get_oi_at(history: list, hours_ago: float) -> float | None:
    if not history:
        return None
    target_ts = time.time() - (hours_ago * 3600)
    closest = min(history, key=lambda h: abs(h["ts"] - target_ts))
    if abs(closest["ts"] - target_ts) > 1800:
        return None
    return closest["oi"]


# ---------------------------------------------------------------------------
# MCP Helper — uses mcporter CLI subprocess (matches all other skills)
# ---------------------------------------------------------------------------

def mcporter_call(tool_name: str, params: dict = None, retries: int = 2,
                  timeout: int = 25) -> dict:
    """Call a Senpi MCP tool via mcporter CLI."""
    params = params or {}
    args = json.dumps(params) if params else "{}"
    cmd = ["mcporter", "call", "senpi", tool_name, "--args", args]
    for attempt in range(retries + 1):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if r.returncode != 0:
                if attempt < retries:
                    time.sleep(2)
                    continue
                return {}
            raw = json.loads(r.stdout)
            # Unwrap MCP content envelope
            if isinstance(raw, dict) and "content" in raw:
                content = raw["content"]
                if isinstance(content, list) and content:
                    first = content[0]
                    if isinstance(first, dict) and "text" in first:
                        try:
                            return json.loads(first["text"])
                        except (json.JSONDecodeError, TypeError):
                            pass
            return raw
        except subprocess.TimeoutExpired:
            if attempt < retries:
                time.sleep(2)
                continue
            return {}
        except (json.JSONDecodeError, Exception) as e:
            if attempt < retries:
                time.sleep(2)
                continue
            log(f"MCP call {tool_name} failed: {e}")
            return {}
    return {}


# ---------------------------------------------------------------------------
# Position Helper — correct clearinghouse unwrapping
# ---------------------------------------------------------------------------

def get_positions(wallet: str = None) -> list:
    """Get current open positions. Correctly unwraps main/xyz nesting."""
    if not wallet:
        wallet, _ = get_wallet_and_strategy()
    if not wallet:
        return []
    result = mcporter_call("strategy_get_clearinghouse_state",
                           {"strategy_wallet": wallet})
    if not result or not isinstance(result, dict):
        return []

    data = result.get("data", result)
    positions = []
    for section in ("main", "xyz"):
        s = data.get(section, {})
        if not isinstance(s, dict):
            continue
        for ap in s.get("assetPositions", []):
            pos = ap.get("position", ap)
            szi = float(pos.get("szi", pos.get("size", 0)))
            if szi == 0:
                continue
            positions.append({
                "coin": pos.get("coin", ""),
                "direction": "LONG" if szi > 0 else "SHORT",
                "szi": szi,
                "upnl": float(pos.get("unrealizedPnl", 0)),
                "margin": float(pos.get("marginUsed", 0)),
                "entryPrice": float(pos.get("entryPx", 0)),
                "markPrice": float(pos.get("markPx", 0)),
                "size": abs(szi),
                "leverage": float(
                    pos.get("leverage", {}).get("value", 10)
                    if isinstance(pos.get("leverage"), dict)
                    else pos.get("leverage", 10)
                ),
            })
    return positions


def get_wallet_balance(wallet: str = None) -> float:
    """Get wallet balance. Correctly unwraps main.marginSummary."""
    if not wallet:
        wallet, _ = get_wallet_and_strategy()
    if not wallet:
        return 0.0
    result = mcporter_call("strategy_get_clearinghouse_state",
                           {"strategy_wallet": wallet})
    if not result or not isinstance(result, dict):
        return 0.0

    data = result.get("data", result)
    total = 0.0
    for section in ("main", "xyz"):
        s = data.get(section, {})
        if not isinstance(s, dict):
            continue
        ms = s.get("marginSummary", {})
        if isinstance(ms, dict):
            val = ms.get("accountValue", ms.get("equity", 0))
            try:
                total += float(val)
            except (TypeError, ValueError):
                pass
    return total


def get_deployed_margin(positions: list) -> float:
    """Calculate total margin currently deployed."""
    total = 0.0
    for pos in positions:
        margin = float(pos.get("margin", pos.get("marginUsed", 0)))
        if margin > 0:
            total += margin
        else:
            szi = abs(float(pos.get("szi", pos.get("size", 0))))
            entry = float(pos.get("entryPrice", pos.get("entryPx", 0)))
            leverage = float(pos.get("leverage", 1))
            if entry > 0 and leverage > 0:
                total += (szi * entry) / leverage
    return total


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def output(data: dict) -> None:
    print(json.dumps(data, indent=2, default=str))
    sys.stdout.flush()


def log(msg: str) -> None:
    print(f"[HYDRA] {msg}", file=sys.stderr)
