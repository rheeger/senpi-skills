"""WOLVERINE v2.0 — Config Helper.
Self-contained. Scanner-entry-only, DSL-exit-only architecture."""
# Copyright 2026 Senpi (https://senpi.ai)
# Licensed under MIT

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = os.environ.get("OPENCLAW_WORKSPACE", "/data/workspace")
SKILL_DIR = Path(WORKSPACE) / "skills" / "wolverine-strategy"
CONFIG_PATH = SKILL_DIR / "config" / "wolverine-config.json"
STATE_DIR = SKILL_DIR / "state"

STATE_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write(path, data):
    path = str(path)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def get_wallet_and_strategy():
    w = os.environ.get("WOLVERINE_WALLET", "")
    s = os.environ.get("WOLVERINE_STRATEGY_ID", "")
    if not w or not s:
        c = load_config()
        w = w or c.get("wallet", "")
        s = s or c.get("strategyId", "")
    return w, s


# ─── Scan History ────────────────────────────────────────────

def load_scan_history():
    p = STATE_DIR / "scan-history.json"
    if p.exists():
        try:
            with open(p) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"scans": []}


def save_scan_history(history):
    scans = history.get("scans", [])
    if len(scans) > 60:
        history["scans"] = scans[-60:]
    atomic_write(str(STATE_DIR / "scan-history.json"), history)


# ─── Trade Counter ───────────────────────────────────────────

def load_trade_counter():
    p = STATE_DIR / "trade-counter.json"
    if p.exists():
        try:
            with open(p) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"date": now_date(), "entries": 0, "dailyLoss": 0}


def save_trade_counter(tc):
    if tc.get("date") != now_date():
        tc["date"] = now_date()
        tc["entries"] = 0
        tc["dailyLoss"] = 0
    atomic_write(str(STATE_DIR / "trade-counter.json"), tc)


# ─── Cooldown ────────────────────────────────────────────────

def is_asset_cooled_down(coin, minutes=120):
    p = STATE_DIR / "cooldowns.json"
    if not p.exists():
        return False
    try:
        with open(p) as f:
            cooldowns = json.load(f)
    except (json.JSONDecodeError, IOError):
        return False
    entry = cooldowns.get(coin)
    if not entry:
        return False
    return time.time() < entry.get("until", 0)


def set_cooldown(coin, minutes=120):
    p = STATE_DIR / "cooldowns.json"
    cooldowns = {}
    if p.exists():
        try:
            with open(p) as f:
                cooldowns = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    cooldowns[coin] = {"until": time.time() + minutes * 60, "set_at": now_iso()}
    atomic_write(str(p), cooldowns)


# ─── MCP ─────────────────────────────────────────────────────

def mcporter_call(tool, retries=2, timeout=25, **params):
    args = json.dumps(params) if params else "{}"
    cmd = ["mcporter", "call", "senpi", tool, "--args", args]
    for attempt in range(retries):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if r.returncode != 0:
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
                return None
            raw = json.loads(r.stdout)
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
            if attempt < retries - 1:
                time.sleep(1)
                continue
            return None
        except (json.JSONDecodeError, Exception):
            return None
    return None


def get_positions(wallet=None):
    if not wallet:
        wallet, _ = get_wallet_and_strategy()
    if not wallet:
        return []
    ch = mcporter_call("strategy_get_clearinghouse_state", strategy_wallet=wallet)
    if not ch or not isinstance(ch, dict):
        return []
    data = ch.get("data", ch)
    positions = []
    for section in ("main", "xyz"):
        s = data.get(section, {})
        if not isinstance(s, dict):
            continue
        for ap in s.get("assetPositions", []):
            pos = ap.get("position", ap)
            szi = float(pos.get("szi", 0))
            if szi == 0:
                continue
            positions.append({
                "coin": pos.get("coin", ""),
                "direction": "LONG" if szi > 0 else "SHORT",
                "szi": szi,
                "size": abs(szi),
                "margin": float(pos.get("marginUsed", 0)),
                "entryPrice": float(pos.get("entryPx", 0)),
                "markPrice": float(pos.get("markPx", 0)),
                "leverage": float(
                    pos.get("leverage", {}).get("value", 7)
                    if isinstance(pos.get("leverage"), dict)
                    else pos.get("leverage", 7)
                ),
                "upnl": float(pos.get("unrealizedPnl", 0)),
            })
    return positions


def output(data):
    print(json.dumps(data, default=str))
    sys.stdout.flush()


def log(msg):
    print(f"[WOLVERINE] {msg}", file=sys.stderr)


def now_ts():
    return time.time()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def now_date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
