#!/usr/bin/env python3
"""
Smart Money Flip Detector v3 — FOX v0.2 Multi-strategy
Checks if SM direction has flipped against any active positions across ALL strategies.
Runs every 5 min. Outputs JSON with action_required + notifications.

Usage: python3 fox-sm-flip-check.py
"""

import json, sys, os, glob
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fox_config import (load_all_strategies, load_strategy, dsl_state_glob,
                         mcporter_call, heartbeat)


def get_active_positions():
    """Read all active DSL state files across ALL strategies."""
    positions = []
    for key, cfg in load_all_strategies().items():
        wallet = cfg.get("wallet", "")
        for f in glob.glob(dsl_state_glob(key)):
            try:
                with open(f) as fh:
                    state = json.load(fh)
                if state.get("active"):
                    positions.append({
                        "asset": state["asset"],
                        "direction": state["direction"],
                        "strategyKey": key,
                        "wallet": wallet,
                        "file": f
                    })
            except (json.JSONDecodeError, IOError, KeyError, AttributeError):
                continue
    return positions


def get_sm_data():
    """Fetch smart money data via leaderboard_get_markets."""
    return mcporter_call("leaderboard_get_markets")


def analyze(positions, sm_data):
    """Check for SM flips against our positions."""
    alerts = []
    action_required = []
    notifications = []

    markets = sm_data.get("markets", {}).get("markets", [])
    if not isinstance(markets, list):
        return {"error": "unexpected SM data format", "raw_keys": str(type(markets)),
                "action_required": [], "notifications": []}

    # Build asset->SM map
    sm_map = {}
    for m in markets:
        asset = m.get("token") or m.get("asset") or m.get("coin", "")
        if not asset:
            continue
        raw_pnl = m.get("pct_of_top_traders_gain")
        if raw_pnl is not None:
            pnl_pct = float(raw_pnl or 0) * 100
        else:
            pnl_pct = float(m.get("pnlContribution", 0) or 0)
        traders = int(m.get("trader_count", m.get("traderCount", 0)) or 0)
        direction = (m.get("direction") or "").upper()

        avg_at_peak = float(m.get("avgAtPeak", 50) or 50)
        near_peak_pct = float(m.get("nearPeakPct", 0) or 0)

        key = asset.upper()
        if key not in sm_map or abs(pnl_pct) > abs(sm_map[key].get("pnlPct", 0)):
            sm_map[key] = {
                "direction": direction,
                "pnlPct": pnl_pct,
                "traders": traders,
                "avgAtPeak": avg_at_peak,
                "nearPeakPct": near_peak_pct
            }

    for pos in positions:
        asset = pos["asset"].upper()
        sm = sm_map.get(asset)
        if not sm:
            continue

        my_dir = pos["direction"].upper()
        sm_dir = sm["direction"]

        flipped = (my_dir == "LONG" and sm_dir == "SHORT") or \
                  (my_dir == "SHORT" and sm_dir == "LONG")

        # Conviction scoring
        conviction = 0
        if sm["pnlPct"] > 5: conviction += 2
        elif sm["pnlPct"] > 1: conviction += 1
        if sm["traders"] > 100: conviction += 2
        elif sm["traders"] > 30: conviction += 1
        if sm["nearPeakPct"] > 50: conviction += 2
        elif sm["nearPeakPct"] > 20: conviction += 1
        if sm["avgAtPeak"] > 80: conviction += 1

        alert_level = "none"
        if flipped and conviction >= 4:
            alert_level = "FLIP_NOW"
        elif flipped and conviction >= 2:
            alert_level = "FLIP_WARNING"
        elif flipped:
            alert_level = "WATCH"

        if flipped:
            alert_entry = {
                "asset": asset,
                "myDirection": my_dir,
                "smDirection": sm_dir,
                "flipped": flipped,
                "alertLevel": alert_level,
                "conviction": conviction,
                "smPnlPct": sm["pnlPct"],
                "smTraders": sm["traders"],
                "avgAtPeak": sm["avgAtPeak"],
                "nearPeakPct": sm["nearPeakPct"],
                "strategyKey": pos["strategyKey"]
            }
            alerts.append(alert_entry)

            # FLIP_NOW → action_required + notification
            if alert_level == "FLIP_NOW":
                action_required.append({
                    "action": "close_position",
                    "coin": asset,
                    "strategyKey": pos["strategyKey"],
                    "wallet": pos.get("wallet", ""),
                    "direction": my_dir,
                    "reason": f"SM flip detected, conviction {conviction}"
                })
                notifications.append(
                    f"SM FLIP [{pos['strategyKey']}]: {asset} {my_dir} -> "
                    f"SM now {sm_dir} (conviction {conviction})"
                )

    return {
        "time": datetime.now(timezone.utc).isoformat(),
        "positions": len(positions),
        "alerts": alerts,
        "hasFlipSignal": any(a["alertLevel"] in ("FLIP_NOW", "FLIP_WARNING") for a in alerts),
        "action_required": action_required,
        "notifications": notifications,
    }


if __name__ == "__main__":
    heartbeat("sm_flip")
    positions = get_active_positions()
    if not positions:
        print(json.dumps({
            "time": datetime.now(timezone.utc).isoformat(),
            "positions": 0, "alerts": [], "hasFlipSignal": False,
            "action_required": [], "notifications": []
        }))
        sys.exit(0)

    try:
        sm_data = get_sm_data()
    except Exception as e:
        print(json.dumps({"error": f"sm_fetch_failed: {e}", "hasFlipSignal": False,
                          "action_required": [], "notifications": []}))
        sys.exit(1)
    result = analyze(positions, sm_data)
    print(json.dumps(result))
