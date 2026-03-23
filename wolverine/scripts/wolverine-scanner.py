#!/usr/bin/env python3
# Senpi WOLVERINE Scanner v2.0
# Copyright 2026 Senpi (https://senpi.ai)
# Licensed under MIT
# Source: https://github.com/Senpi-ai/senpi-skills
"""WOLVERINE v2.0 — HYPE Alpha Hunter. Entry-Only Scanner.

v2.0 removes the scanner thesis exit entirely. The lesson from v1.1:
25 of 27 trades were killed by the scanner's thesis exit, not by DSL.
The scanner constantly re-evaluated SM flow and aborted positions on every
wobble. On HYPE, which wobbles every 10 minutes, this meant the scanner
was chopping its own winners before they could run.

Trade #6 proved the thesis: HYPE LONG, +29.92% ROE, held 757 minutes.
The scanner let that one ride and it was a monster. If even 2-3 more
trades had been allowed to run, Wolverine would be deeply profitable.

The fix: SCANNER DECIDES ENTRIES. DSL MANAGES EXITS.
Once a position is open, only DSL can close it (floor, timeout, trailing
tier, stagnation TP). The scanner never re-evaluates open positions.

Entry requirements are raised: score 8+ with multi-timeframe agreement
(4H + 1H aligned). Fewer entries, wider stops, let HYPE be HYPE.

Leverage lowered to 7x (from 10x). At 7x, a 2% move = 14% ROE.
A 4% move = 28% ROE. That's plenty of upside with more room to breathe.

Uses: leaderboard_get_markets (SM consensus on HYPE)
Runs every 3 minutes.
"""

import json
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wolverine_config as cfg


# ═══════════════════════════════════════════════════════════════
# HARDCODED CONSTANTS
# ═══════════════════════════════════════════════════════════════

ASSET = "HYPE"                     # Single-asset hunter
MIN_LEVERAGE = 5
MAX_LEVERAGE = 7                   # Lowered from 10x — HYPE is volatile enough
DEFAULT_LEVERAGE = 7
MAX_POSITIONS = 1                  # One HYPE position at a time
MAX_DAILY_ENTRIES = 4              # Max 4 entries/day — patience is the edge
MAX_DAILY_LOSS_PCT = 10            # Daily loss circuit breaker
COOLDOWN_MINUTES = 180             # 3 hours between entries (not 2)

# Entry thresholds — raised from v1.1
MIN_SCORE = 8                      # Was effectively ~5 in v1.1. Now 8.
MIN_SM_TRADERS = 15                # Minimum SM traders on HYPE
MIN_SM_RANK = 30                   # HYPE must be in top 30 of SM leaderboard
REQUIRE_4H_1H_ALIGNMENT = True     # Both timeframes must agree on direction

# XYZ ban
XYZ_BANNED = True

# DSL configuration — wide for HYPE's volatility
# Scanner generates these in the DSL state file. DSL manages ALL exits.
DSL_CONFIG = {
    "lockMode": "pct_of_high_water",
    "phase2TriggerRoe": 15,        # Don't start trailing until +15% ROE
    "phase1": {
        "consecutiveBreachesRequired": 3,
        "phase1MaxMinutes": 120,    # 2 hours — give HYPE time to move
        "weakPeakCutMinutes": 60,   # 1 hour weak peak tolerance
        "deadWeightCutMin": 45,     # 45 min dead weight
        "absoluteFloorRoe": -20,    # Wide floor — 20% loss at 7x = 2.85% price move
        "retraceThreshold": 0.25,   # 25% retrace from entry peak
    },
    "tiers": [
        {"triggerPct": 15, "lockHwPct": 30, "consecutiveBreachesRequired": 3},
        {"triggerPct": 25, "lockHwPct": 50, "consecutiveBreachesRequired": 2},
        {"triggerPct": 40, "lockHwPct": 65, "consecutiveBreachesRequired": 1},
        {"triggerPct": 60, "lockHwPct": 75, "consecutiveBreachesRequired": 1},
        {"triggerPct": 80, "lockHwPct": 85, "consecutiveBreachesRequired": 1},
    ],
    "stagnationTp": {"enabled": True, "roeMin": 15, "hwStaleMin": 60},
    "execution": {
        "phase1SlOrderType": "MARKET",
        "phase2SlOrderType": "MARKET",
        "breachCloseOrderType": "MARKET",
    },
}

# Conviction tiers for Phase 1 timing
CONVICTION_TIERS = [
    {"minScore": 8,  "absoluteFloorRoe": -20, "phase1MaxMinutes": 120, "weakPeakCutMin": 60, "deadWeightCutMin": 45},
    {"minScore": 10, "absoluteFloorRoe": -25, "phase1MaxMinutes": 180, "weakPeakCutMin": 90, "deadWeightCutMin": 60},
]


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def is_xyz(asset):
    return asset.lower().startswith("xyz")


# ═══════════════════════════════════════════════════════════════
# SIGNAL SCORING
# ═══════════════════════════════════════════════════════════════

def score_hype_signal(markets_data):
    """Score HYPE from leaderboard_get_markets data.
    Returns (score, direction, reasons) or (0, None, [])."""

    hype_data = None
    for m in markets_data:
        if not isinstance(m, dict):
            continue
        token = str(m.get("token", m.get("asset", ""))).upper()
        dex = str(m.get("dex", "")).lower()
        if token == ASSET and dex != "xyz":
            hype_data = m
            break

    if not hype_data:
        return 0, None, []

    score = 0
    reasons = []

    # SM direction and trader count
    sm_direction = str(hype_data.get("direction", "")).lower()
    trader_count = int(hype_data.get("trader_count", 0))
    sm_rank = int(hype_data.get("rank", hype_data.get("position", 999)))
    contribution = safe_float(hype_data.get("pct_of_top_traders_gain", 0))
    contrib_change = safe_float(hype_data.get("contribution_pct_change_4h", 0))

    if not sm_direction or sm_direction not in ("long", "short"):
        return 0, None, []

    direction = sm_direction

    # Gate: minimum traders
    if trader_count < MIN_SM_TRADERS:
        return 0, None, []

    # Gate: minimum SM rank
    if sm_rank > MIN_SM_RANK:
        return 0, None, []

    # ── Scoring ──

    # SM presence (base)
    score += 2
    reasons.append(f"SM_{direction.upper()} rank#{sm_rank} ({trader_count} traders)")

    # Trader count depth
    if trader_count >= 40:
        score += 2
        reasons.append(f"DEEP_SM ({trader_count} traders)")
    elif trader_count >= 25:
        score += 1
        reasons.append(f"SOLID_SM ({trader_count} traders)")

    # Contribution strength
    if contribution >= 5.0:
        score += 2
        reasons.append(f"HIGH_CONTRIB {contribution:.1f}%")
    elif contribution >= 2.0:
        score += 1
        reasons.append(f"MODERATE_CONTRIB {contribution:.1f}%")

    # Contribution acceleration (gen-2 signal)
    if contrib_change > 0.003:
        score += 2
        reasons.append(f"CONTRIB_ACCEL +{contrib_change * 100:.3f}%/4h")
    elif contrib_change > 0.001:
        score += 1
        reasons.append(f"CONTRIB_BUILDING +{contrib_change * 100:.3f}%/4h")

    # Price momentum alignment
    price_4h = safe_float(hype_data.get("token_price_change_pct_4h", 0))
    price_1h = safe_float(hype_data.get("token_price_change_pct_1h",
                          hype_data.get("price_change_1h", 0)))

    if direction == "long":
        if price_4h > 0 and price_1h > 0:
            score += 2
            reasons.append(f"4H_1H_ALIGNED (+{price_4h:.1f}%/+{price_1h:.1f}%)")
        elif price_4h > 0:
            score += 1
            reasons.append(f"4H_ALIGNED (+{price_4h:.1f}%)")
    else:
        if price_4h < 0 and price_1h < 0:
            score += 2
            reasons.append(f"4H_1H_ALIGNED ({price_4h:.1f}%/{price_1h:.1f}%)")
        elif price_4h < 0:
            score += 1
            reasons.append(f"4H_ALIGNED ({price_4h:.1f}%)")

    # 4H/1H alignment gate
    if REQUIRE_4H_1H_ALIGNMENT:
        if direction == "long" and (price_4h <= 0 or price_1h <= 0):
            return 0, None, [f"4H_1H_NOT_ALIGNED (4h={price_4h:.1f}%, 1h={price_1h:.1f}%)"]
        if direction == "short" and (price_4h >= 0 or price_1h >= 0):
            return 0, None, [f"4H_1H_NOT_ALIGNED (4h={price_4h:.1f}%, 1h={price_1h:.1f}%)"]

    # Volume confirmation
    volume = safe_float(hype_data.get("volume", hype_data.get("volume_24h", 0)))
    avg_volume = safe_float(hype_data.get("avg_volume_6h", hype_data.get("avgVolume", 0)))
    if avg_volume > 0 and volume > avg_volume * 1.2:
        score += 1
        reasons.append(f"VOLUME_UP ({volume / avg_volume:.1f}x)")

    return score, direction, reasons


# ═══════════════════════════════════════════════════════════════
# DSL STATE BUILDER
# ═══════════════════════════════════════════════════════════════

def build_dsl_state(direction, score, leverage):
    """Build COMPLETE DSL state. Scanner generates, agent writes directly.
    NO thesis exit. DSL is the ONLY exit mechanism."""

    # Select conviction tier for Phase 1 timing
    tier = CONVICTION_TIERS[0]  # default
    for t in CONVICTION_TIERS:
        if score >= t["minScore"]:
            tier = t

    wallet, strategy_id = cfg.get_wallet_and_strategy()

    return {
        "active": True,
        "asset": ASSET,
        "direction": direction,
        "score": score,
        "phase": 1,
        "highWaterPrice": None,
        "highWaterRoe": None,
        "currentTierIndex": -1,
        "consecutiveBreaches": 0,
        # Wallet info — prevents DSL Bug #1
        "wallet": wallet,
        "strategyWalletAddress": wallet,
        "strategyId": strategy_id,
        # Phase 1
        "lockMode": DSL_CONFIG["lockMode"],
        "phase2TriggerRoe": DSL_CONFIG["phase2TriggerRoe"],
        "phase1": {
            "enabled": True,
            "retraceThreshold": DSL_CONFIG["phase1"]["retraceThreshold"],
            "consecutiveBreachesRequired": DSL_CONFIG["phase1"]["consecutiveBreachesRequired"],
            "phase1MaxMinutes": tier["phase1MaxMinutes"],
            "weakPeakCutMinutes": tier["weakPeakCutMin"],
            "deadWeightCutMin": tier["deadWeightCutMin"],
            "absoluteFloorRoe": tier["absoluteFloorRoe"],
            "weakPeakCut": {
                "enabled": True,
                "intervalInMinutes": tier["weakPeakCutMin"],
                "minValue": 3.0,
            },
        },
        # Phase 2
        "phase2": {
            "enabled": True,
            "retraceThreshold": 0.015,
            "consecutiveBreachesRequired": 2,
        },
        # Trailing tiers — wide for HYPE
        "tiers": DSL_CONFIG["tiers"],
        "stagnationTp": DSL_CONFIG["stagnationTp"],
        "execution": DSL_CONFIG["execution"],
        # v2.0 flag — tells the agent NOT to thesis-exit
        "_v2_no_thesis_exit": True,
        "_note": "DSL manages ALL exits. Scanner does NOT re-evaluate open positions.",
    }


# ═══════════════════════════════════════════════════════════════
# MAIN SCANNER
# ═══════════════════════════════════════════════════════════════

def run():
    config = cfg.load_config()
    wallet, strategy_id = cfg.get_wallet_and_strategy()

    if not wallet:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY", "note": "no wallet"})
        return

    # ── Check existing positions ──────────────────────────────
    positions = cfg.get_positions(wallet)
    hype_positions = [p for p in positions if p["coin"].upper() == ASSET]

    if len(hype_positions) >= MAX_POSITIONS:
        # Already in a HYPE position. Do NOT re-evaluate. Do NOT thesis exit.
        # DSL handles everything from here.
        cfg.output({
            "status": "ok",
            "heartbeat": "NO_REPLY",
            "note": f"HYPE position active. DSL manages exit. Scanner does NOT re-evaluate.",
            "activePosition": {
                "direction": hype_positions[0]["direction"],
                "entryPrice": hype_positions[0]["entryPrice"],
                "markPrice": hype_positions[0]["markPrice"],
                "upnl": hype_positions[0]["upnl"],
                "margin": hype_positions[0]["margin"],
            },
            "_v2_no_thesis_exit": True,
        })
        return

    # ── Daily limits ──────────────────────────────────────────
    tc = cfg.load_trade_counter()
    if tc.get("entries", 0) >= MAX_DAILY_ENTRIES:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                     "note": f"Daily entry limit ({MAX_DAILY_ENTRIES}) reached"})
        return

    # ── Cooldown ──────────────────────────────────────────────
    if cfg.is_asset_cooled_down(ASSET, COOLDOWN_MINUTES):
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                     "note": f"HYPE on cooldown ({COOLDOWN_MINUTES} min)"})
        return

    # ── Fetch SM data ─────────────────────────────────────────
    raw = cfg.mcporter_call("leaderboard_get_markets")
    if not raw:
        cfg.output({"status": "error", "error": "failed to fetch markets"})
        return

    markets = []
    if isinstance(raw, dict):
        markets = raw.get("markets", raw.get("data", []))
    elif isinstance(raw, list):
        markets = raw

    # ── Score HYPE ────────────────────────────────────────────
    score, direction, reasons = score_hype_signal(markets)

    if score < MIN_SCORE or not direction:
        cfg.output({
            "status": "ok",
            "heartbeat": "NO_REPLY",
            "note": f"HYPE score {score} < {MIN_SCORE}. Waiting.",
            "score": score,
            "reasons": reasons,
        })
        return

    # ── Build entry signal ────────────────────────────────────
    leverage = DEFAULT_LEVERAGE
    margin_pct = 0.30 if score >= 10 else 0.20  # 30% at high conviction, 20% at base

    dsl_state = build_dsl_state(direction, score, leverage)

    # Update trade counter
    tc["entries"] = tc.get("entries", 0) + 1
    cfg.save_trade_counter(tc)

    cfg.output({
        "status": "ok",
        "signal": {
            "asset": ASSET,
            "direction": direction,
            "score": score,
            "mode": "LIFECYCLE",
            "reasons": reasons,
        },
        "entry": {
            "asset": ASSET,
            "direction": direction,
            "leverage": leverage,
            "marginPercent": margin_pct * 100,
            "orderType": "FEE_OPTIMIZED_LIMIT",
        },
        "dslState": dsl_state,
        "constraints": {
            "maxPositions": MAX_POSITIONS,
            "maxLeverage": MAX_LEVERAGE,
            "minLeverage": MIN_LEVERAGE,
            "maxDailyEntries": MAX_DAILY_ENTRIES,
            "cooldownMinutes": COOLDOWN_MINUTES,
            "xyzBanned": XYZ_BANNED,
            "_v2_no_thesis_exit": True,
            "_note": "DSL manages ALL exits. Do NOT re-evaluate or thesis-exit open positions.",
        },
    })


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        cfg.log(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        cfg.output({"status": "error", "error": str(e)})
