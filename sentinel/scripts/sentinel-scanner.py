#!/usr/bin/env python3
# Senpi SENTINEL Scanner v1.0
# Copyright 2026 Senpi (https://senpi.ai)
# Licensed under MIT
# Source: https://github.com/Senpi-ai/senpi-skills
"""SENTINEL v1.0 — Quality Trader Convergence Scanner.

The problem with watching the top 20 traders: by the time 3+ of them show up
on the same asset, the move is already mature. We need to catch the trade BEFORE
those traders reach the top of the leaderboard.

SENTINEL inverts the pipeline:

1. Find assets where SM is BUILDING (contribution_pct_change_4h rising, rank 10-40)
   — these are the assets that WILL be in the top 5 in an hour
2. For the best candidates, check momentum events to see WHO is profiting
   — TCS/TAS/TRP tags tell us if they're quality traders
3. When an asset has rising SM + multiple quality traders confirmed → enter

This catches the window between "SM starts accumulating" and "the asset hits the
top of the leaderboard." Orca catches the rank climbing. SENTINEL catches the
quality traders behind the climbing — and enters with higher conviction because
the people driving the move are proven performers.

Three data sources, one signal:
- leaderboard_get_markets → where SM interest is accelerating
- leaderboard_get_momentum_events → who is profiting and are they good
- leaderboard_get_top → cross-check for convergence confirmation

Uses 2-3 API calls per scan. Runs every 3 minutes.
"""

import json
import sys
import os
import time
from datetime import datetime, timezone, timedelta
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sentinel_config as cfg

# ─── Constants ────────────────────────────────────────────────

MAX_LEVERAGE = 10
MIN_LEVERAGE = 5
MAX_POSITIONS = 3
MAX_DAILY_ENTRIES = 5
XYZ_BANNED = True

# Step 1: Asset discovery from leaderboard
MIN_RANK = 6                          # Not already peaked
MAX_RANK = 40                         # Has meaningful SM attention
MIN_CONTRIBUTION_PCT = 2.0            # Real SM share
MIN_CONTRIBUTION_CHANGE_4H = 3.0      # SM must be actively building
MIN_TRADER_COUNT = 25                 # Broad base

# Step 2: Momentum event quality check
MOMENTUM_LOOKBACK_MINUTES = 60        # Wider window — we want to see who's been profiting
QUALITY_TCS = {"elite", "reliable"}
QUALITY_TRP = {"sniper", "aggressive", "balanced"}
MIN_QUALITY_TRADERS = 2               # At least 2 quality traders confirmed on the asset
MIN_CONCENTRATION = 0.4               # Trader gains must be somewhat concentrated

# Step 3: Top trader cross-check
TOP_TRADERS_LIMIT = 30                # Check wider range for convergence
MIN_TOP_TRADER_APPEARANCES = 1        # At least 1 top trader also in this asset

# DSL
SENTINEL_DSL_TIERS = [
    {"triggerPct": 5,  "lockHwPct": 30, "consecutiveBreachesRequired": 3},
    {"triggerPct": 10, "lockHwPct": 50, "consecutiveBreachesRequired": 2},
    {"triggerPct": 15, "lockHwPct": 70, "consecutiveBreachesRequired": 2},
    {"triggerPct": 20, "lockHwPct": 80, "consecutiveBreachesRequired": 1},
    {"triggerPct": 30, "lockHwPct": 85, "consecutiveBreachesRequired": 1},
]

SENTINEL_STAGNATION_TP = {"enabled": True, "roeMin": 10, "hwStaleMin": 40}


# ─── Step 1: Find Rising Assets ──────────────────────────────

def find_rising_assets():
    """Find assets where SM interest is building — the FUTURE top 5."""
    data = cfg.mcporter_call("leaderboard_get_markets", limit=100)
    if not data or not data.get("success"):
        return []

    markets_data = data.get("data", data)
    if isinstance(markets_data, dict):
        markets_data = markets_data.get("markets", markets_data)
    if isinstance(markets_data, dict):
        markets_data = markets_data.get("markets", [])

    candidates = []
    for i, m in enumerate(markets_data):
        if not isinstance(m, dict):
            continue

        token = m.get("token", "")
        dex = m.get("dex", "")
        rank = i + 1

        if XYZ_BANNED and (dex.lower() == "xyz" or token.lower().startswith("xyz:")):
            continue
        if rank < MIN_RANK or rank > MAX_RANK:
            continue

        contribution = float(m.get("pct_of_top_traders_gain", 0))
        contrib_change = float(m.get("contribution_pct_change_4h", 0))
        price_chg = float(m.get("token_price_change_pct_4h", 0) or 0)
        trader_count = int(m.get("trader_count", 0))
        max_lev = int(m.get("max_leverage", 0))
        direction = m.get("direction", "").upper()

        if contribution < MIN_CONTRIBUTION_PCT:
            continue
        if contrib_change < MIN_CONTRIBUTION_CHANGE_4H:
            continue
        if trader_count < MIN_TRADER_COUNT:
            continue
        if max_lev < MIN_LEVERAGE:
            continue

        # 4H price alignment
        if direction == "LONG" and price_chg < 0:
            continue
        if direction == "SHORT" and price_chg > 0:
            continue

        candidates.append({
            "token": token,
            "dex": dex,
            "rank": rank,
            "direction": direction,
            "contribution": contribution,
            "contrib_change_4h": contrib_change,
            "price_chg_4h": price_chg,
            "trader_count": trader_count,
            "max_leverage": max_lev,
        })

    # Sort by contribution velocity — fastest risers first
    candidates.sort(key=lambda c: c["contrib_change_4h"], reverse=True)
    return candidates[:10]


# ─── Step 2: Check Who's Profiting (Momentum Events) ─────────

def check_quality_traders(asset):
    """For a rising asset, check momentum events to see WHO is profiting on it."""
    now = datetime.now(timezone.utc)
    from_time = (now - timedelta(minutes=MOMENTUM_LOOKBACK_MINUTES)).isoformat()

    quality_confirmations = []

    for tier in [2, 1]:
        data = cfg.mcporter_call("leaderboard_get_momentum_events",
                                  tier=tier, limit=50,
                                  **{"from": from_time, "to": now.isoformat()})
        if not data or not data.get("success"):
            continue

        events_data = data.get("data", data)
        if isinstance(events_data, dict):
            events_data = events_data.get("events", events_data)
        if isinstance(events_data, dict):
            events = events_data.get("events", [])
        elif isinstance(events_data, list):
            events = events_data
        else:
            continue

        seen_traders = {q["trader_id"] for q in quality_confirmations}

        for event in events:
            if not isinstance(event, dict):
                continue

            trader_id = event.get("trader_id", "")
            if trader_id in seen_traders:
                continue

            positions = event.get("top_positions", [])
            asset_match = None
            for pos in positions:
                if pos.get("market", "") == asset:
                    asset_match = pos
                    break
            if not asset_match:
                continue

            tags = event.get("trader_tags", {})
            if not isinstance(tags, dict):
                continue

            tcs = tags.get("tcs", "").strip().lower()
            trp = tags.get("trp", "").strip().lower()
            concentration = float(event.get("concentration", 0))

            if tcs in QUALITY_TCS and trp in QUALITY_TRP and concentration >= MIN_CONCENTRATION:
                quality_confirmations.append({
                    "trader_id": trader_id,
                    "tier": tier,
                    "tcs": tags.get("tcs", ""),
                    "tas": tags.get("tas", ""),
                    "trp": tags.get("trp", ""),
                    "concentration": concentration,
                    "delta_pnl": float(event.get("delta_pnl", 0)),
                    "position_direction": asset_match.get("direction", ""),
                    "position_leverage": asset_match.get("leverage", 0),
                })
                seen_traders.add(trader_id)

    return quality_confirmations


# ─── Step 3: Top Trader Cross-Check ──────────────────────────

def fetch_top_traders():
    data = cfg.mcporter_call("leaderboard_get_top", limit=TOP_TRADERS_LIMIT)
    if not data or not data.get("success"):
        return []
    lb = data.get("data", data)
    if isinstance(lb, dict):
        lb = lb.get("leaderboard", lb)
    if isinstance(lb, dict):
        return lb.get("data", [])
    return lb if isinstance(lb, list) else []


def check_top_trader_presence(asset, top_traders):
    appearances = []
    for t in top_traders:
        if not isinstance(t, dict):
            continue
        if asset in t.get("top_markets", []):
            appearances.append({
                "rank": t.get("rank", 999),
                "pnl": float(t.get("unrealized_pnl", 0)),
            })
    return appearances


# ─── Scoring ──────────────────────────────────────────────────

def score_signal(candidate, quality_traders, top_appearances):
    score = 0
    reasons = []

    # Layer 1: SM velocity
    cc = candidate["contrib_change_4h"]
    if cc >= 20:
        score += 3
        reasons.append(f"SURGING_SM +{cc:.1f}% contrib velocity")
    elif cc >= 10:
        score += 2
        reasons.append(f"FAST_SM +{cc:.1f}% contrib velocity")
    else:
        score += 1
        reasons.append(f"RISING_SM +{cc:.1f}% contrib velocity")

    if candidate["rank"] <= 15:
        score += 2
        reasons.append(f"STRONG_RANK #{candidate['rank']}")
    elif candidate["rank"] <= 25:
        score += 1
        reasons.append(f"MID_RANK #{candidate['rank']}")

    if candidate["trader_count"] >= 100:
        score += 1
        reasons.append(f"DEEP_SM {candidate['trader_count']} traders")

    if abs(candidate["price_chg_4h"]) < 2:
        score += 1
        reasons.append(f"PRICE_LAG {candidate['price_chg_4h']:+.1f}%")

    # Layer 2: Quality traders (the differentiator)
    qt_count = len(quality_traders)
    if qt_count >= 4:
        score += 5
        reasons.append(f"ELITE_CONVERGENCE {qt_count} quality traders")
    elif qt_count >= 3:
        score += 4
        reasons.append(f"STRONG_CONVERGENCE {qt_count} quality traders")
    elif qt_count >= 2:
        score += 3
        reasons.append(f"CONVERGENCE {qt_count} quality traders")

    tier2_count = sum(1 for qt in quality_traders if qt["tier"] == 2)
    if tier2_count >= 2:
        score += 2
        reasons.append(f"TIER2_DOUBLE {tier2_count} Tier 2 events")
    elif tier2_count >= 1:
        score += 1
        reasons.append(f"TIER2_CONFIRMED")

    avg_conc = sum(qt["concentration"] for qt in quality_traders) / len(quality_traders) if quality_traders else 0
    if avg_conc > 0.7:
        score += 1
        reasons.append(f"HIGH_CONVICTION {avg_conc:.0%} avg concentration")

    # Layer 3: Top trader bonus
    if top_appearances:
        if len(top_appearances) >= 2:
            score += 2
            reasons.append(f"TOP_CONFIRMED {len(top_appearances)} in top {TOP_TRADERS_LIMIT}")
        else:
            score += 1
            reasons.append(f"TOP_PRESENT rank #{top_appearances[0]['rank']}")

    return score, reasons


# ─── DSL State Builder ────────────────────────────────────────

def build_dsl_state_template(asset, direction, score):
    if score >= 12:
        timeout, weak_peak, dead_weight, floor_roe = 60, 30, 20, -25
    elif score >= 9:
        timeout, weak_peak, dead_weight, floor_roe = 45, 20, 15, -22
    else:
        timeout, weak_peak, dead_weight, floor_roe = 35, 15, 12, -20

    return {
        "active": True, "asset": asset, "direction": direction, "score": score,
        "phase": 1, "highWaterPrice": None, "highWaterRoe": None,
        "currentTierIndex": -1, "consecutiveBreaches": 0,
        "lockMode": "pct_of_high_water", "phase2TriggerRoe": 5,
        "phase1": {
            "enabled": True, "retraceThreshold": 0.03, "consecutiveBreachesRequired": 3,
            "phase1MaxMinutes": timeout, "weakPeakCutMinutes": weak_peak,
            "deadWeightCutMin": dead_weight, "absoluteFloorRoe": floor_roe,
            "weakPeakCut": {"enabled": True, "intervalInMinutes": weak_peak, "minValue": 3.0},
        },
        "phase2": {"enabled": True, "retraceThreshold": 0.015, "consecutiveBreachesRequired": 2},
        "tiers": SENTINEL_DSL_TIERS, "stagnationTp": SENTINEL_STAGNATION_TP,
        "execution": {"phase1SlOrderType": "MARKET", "phase2SlOrderType": "MARKET", "breachCloseOrderType": "MARKET"},
        "_sentinel_version": "1.0",
    }


# ─── Per-Asset Cooldown ──────────────────────────────────────

COOLDOWN_FILE = os.path.join(
    os.environ.get("OPENCLAW_WORKSPACE", "/data/workspace"),
    "skills", "sentinel-strategy", "state", "asset-cooldowns.json"
)

def is_asset_cooled_down(asset, cooldown_minutes=120):
    try:
        if os.path.exists(COOLDOWN_FILE):
            with open(COOLDOWN_FILE) as f:
                cooldowns = json.load(f)
            if asset in cooldowns:
                return (time.time() - cooldowns[asset].get("exitTimestamp", 0)) / 60 < cooldown_minutes
    except (json.JSONDecodeError, IOError):
        pass
    return False


# ─── Main ─────────────────────────────────────────────────────

def run():
    config = cfg.load_config()
    wallet, _ = cfg.get_wallet_and_strategy()

    if not wallet:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY", "note": "no wallet"})
        return

    tc = cfg.load_trade_counter()
    if tc.get("gate") != "OPEN":
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY", "note": f"gate={tc['gate']}"})
        return

    if tc.get("entries", 0) >= config.get("risk", {}).get("maxEntriesPerDay", MAX_DAILY_ENTRIES):
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY", "note": "max entries"})
        return

    account_value, positions = cfg.get_positions(wallet)
    if len(positions) >= MAX_POSITIONS:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY", "note": "max positions"})
        return

    active_coins = {p["coin"] for p in positions}
    cooldown_min = config.get("risk", {}).get("cooldownMinutes", 120)

    # Step 1: Find rising assets
    candidates = find_rising_assets()
    if not candidates:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY", "note": "no rising assets"})
        return

    candidates = [c for c in candidates if c["token"] not in active_coins]
    candidates = [c for c in candidates if not is_asset_cooled_down(c["token"], cooldown_min)]
    if not candidates:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY", "note": "candidates filtered"})
        return

    # Steps 2+3: Check quality traders + top trader cross-check
    top_traders = fetch_top_traders()

    signals = []
    for candidate in candidates[:5]:
        quality_traders = check_quality_traders(candidate["token"])
        matching = [qt for qt in quality_traders if qt["position_direction"].upper() == candidate["direction"]]

        if len(matching) < MIN_QUALITY_TRADERS:
            continue

        top_appearances = check_top_trader_presence(candidate["token"], top_traders)
        score, reasons = score_signal(candidate, matching, top_appearances)

        signals.append({
            "token": candidate["token"], "dex": candidate.get("dex", ""),
            "direction": candidate["direction"], "score": score, "reasons": reasons,
            "leaderboard": {
                "rank": candidate["rank"], "contribution": candidate["contribution"],
                "contrib_change_4h": candidate["contrib_change_4h"],
                "price_chg_4h": candidate["price_chg_4h"],
                "trader_count": candidate["trader_count"], "max_leverage": candidate["max_leverage"],
            },
            "quality_traders": [{"tcs": qt["tcs"], "trp": qt["trp"], "tier": qt["tier"],
                                  "concentration": qt["concentration"]} for qt in matching],
            "top_trader_appearances": len(top_appearances),
        })

    min_score = config.get("entry", {}).get("minScore", 8)
    signals = [s for s in signals if s["score"] >= min_score]
    signals.sort(key=lambda s: s["score"], reverse=True)

    if not signals:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                     "note": f"{len(candidates)} rising, none had {MIN_QUALITY_TRADERS}+ quality traders"})
        return

    best = signals[0]
    margin_pct = 0.35 if best["score"] >= 12 else 0.30 if best["score"] >= 10 else 0.25
    margin = round(account_value * margin_pct, 2)
    leverage = min(best["leaderboard"]["max_leverage"], MAX_LEVERAGE)

    cfg.output({
        "status": "ok", "signal": best,
        "entry": {"coin": best["token"], "direction": best["direction"],
                  "leverage": leverage, "margin": margin, "orderType": "FEE_OPTIMIZED_LIMIT"},
        "dslState": build_dsl_state_template(best["token"], best["direction"], best["score"]),
        "constraints": {"minLeverage": MIN_LEVERAGE, "maxLeverage": MAX_LEVERAGE,
                        "maxPositions": MAX_POSITIONS, "stagnationTp": SENTINEL_STAGNATION_TP},
        "allSignals": signals[:5], "candidatesScanned": len(candidates),
    })


if __name__ == "__main__":
    run()
