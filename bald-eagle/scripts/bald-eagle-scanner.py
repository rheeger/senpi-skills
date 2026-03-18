# Copyright 2026 Senpi (https://senpi.ai)
# Licensed under MIT
# Source: https://github.com/Senpi-ai/senpi-skills

"""
BALD EAGLE v1.0 — XYZ Equities Scanner
========================================
Purpose-built scanner for tokenized US equities/commodities on Hyperliquid's xyz dex.

Pipeline:
  Gate 1: XYZ Universe Filter (leaderboard_get_markets, dex=xyz)
  Gate 2: Signal Confluence (velocity + momentum events + leaderboard top)
  Gate 3: Conviction Scoring (0-12) → DSL state generation

DSL v1.1.1 — scanner generates COMPLETE state. No dsl-profile.json merging.
"""

import sys
import os
from datetime import datetime, timezone

# Ensure local imports work regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bald_eagle_config import (
    load_config, get_positions, mcporter_call, output,
    is_on_cooldown, set_cooldown, load_state, save_state,
    increment_trade, load_trade_counter,
)


# ═══════════════════════════════════════════════════════════════════════════
# Constants (overridden by skill-config.json when available)
# ═══════════════════════════════════════════════════════════════════════════

MIN_TRADER_COUNT = 10
MIN_CONVICTION_SCORE = 6
MAX_POSITIONS = 1
COOLDOWN_MINUTES = 120
LEVERAGE_CAP = 20

# Conviction tiers — maps score range to DSL risk parameters
CONVICTION_TIERS = [
    {"minScore": 6,  "absoluteFloorRoe": -20, "phase1MaxMinutes": 30, "weakPeakCutMin": 15, "deadWeightCutMin": 10},
    {"minScore": 8,  "absoluteFloorRoe": -25, "phase1MaxMinutes": 45, "weakPeakCutMin": 20, "deadWeightCutMin": 15},
    {"minScore": 10, "absoluteFloorRoe": -30, "phase1MaxMinutes": 60, "weakPeakCutMin": 30, "deadWeightCutMin": 20},
]

# Margin sizing by conviction
MARGIN_TIERS = [
    {"minScore": 6,  "maxScore": 7,  "marginPct": 15.0},
    {"minScore": 8,  "maxScore": 9,  "marginPct": 25.0},
    {"minScore": 10, "maxScore": 12, "marginPct": 35.0},
]

# Standard DSL trailing tiers
DSL_TIERS = [
    {"triggerPct": 7,  "lockHwPct": 40, "consecutiveBreachesRequired": 3},
    {"triggerPct": 12, "lockHwPct": 55, "consecutiveBreachesRequired": 2},
    {"triggerPct": 15, "lockHwPct": 75, "consecutiveBreachesRequired": 2},
    {"triggerPct": 20, "lockHwPct": 85, "consecutiveBreachesRequired": 1},
]

# Standard stagnation TP
STAGNATION_TP = {"enabled": True, "roeMin": 10, "hwStaleMin": 45}


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def safe_float(val, default=0.0) -> float:
    """Safely convert to float."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def safe_int(val, default=0) -> int:
    """Safely convert to int."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def log(msg: str) -> None:
    """Print to stderr so stdout stays clean for JSON output."""
    print(f"[BALD EAGLE] {msg}", file=sys.stderr)


def no_reply(note: str) -> dict:
    """Standard heartbeat — no signal."""
    return {"status": "ok", "heartbeat": "NO_REPLY", "note": note}


# ═══════════════════════════════════════════════════════════════════════════
# Gate 1: XYZ Universe Filter
# ═══════════════════════════════════════════════════════════════════════════

def gate1_xyz_universe(config: dict) -> list:
    """
    Call leaderboard_get_markets. Filter for dex == "xyz".
    Returns list of xyz market entries that pass minimum criteria.
    """
    log("Gate 1: Fetching leaderboard_get_markets...")

    raw = mcporter_call("leaderboard_get_markets")

    # isinstance() guard — Senpi returns vary
    if isinstance(raw, dict):
        markets = raw.get("markets", raw.get("data", []))
    elif isinstance(raw, list):
        markets = raw
    else:
        log("Gate 1: Bad response type. SKIP.")
        return []

    if not markets:
        log("Gate 1: No markets returned. SKIP.")
        return []

    # Filter for xyz dex
    scanner_cfg = config.get("scanner", {}).get("gate1", {})
    min_traders = scanner_cfg.get("minTraderCount", MIN_TRADER_COUNT)

    xyz_markets = []
    for m in markets:
        if not isinstance(m, dict):
            continue

        dex = str(m.get("dex", "")).lower()
        if dex != "xyz":
            continue

        token = m.get("token", m.get("asset", m.get("coin", "")))
        trader_count = safe_int(m.get("trader_count", m.get("traderCount", 0)))
        contribution = safe_float(m.get("pct_of_top_traders_gain",
                                        m.get("pctOfTopTradersGain",
                                              m.get("contribution", 0))))

        if trader_count < min_traders:
            log(f"Gate 1: xyz:{token} — {trader_count} traders < {min_traders}. SKIP.")
            continue

        if contribution <= 0:
            log(f"Gate 1: xyz:{token} — zero/negative contribution. SKIP.")
            continue

        direction = str(m.get("direction", "")).lower()
        velocity_4h = safe_float(m.get("contribution_pct_change_4h",
                                       m.get("contributionPctChange4h", 0)))
        price_change_4h = safe_float(m.get("token_price_change_pct_4h",
                                           m.get("tokenPriceChangePct4h", 0)))
        max_leverage = safe_float(m.get("max_leverage",
                                        m.get("maxLeverage", LEVERAGE_CAP)))

        entry = {
            "token": token,
            "dex": "xyz",
            "direction": direction if direction in ("long", "short") else "long",
            "contribution": contribution,
            "velocity_4h": velocity_4h,
            "price_change_4h": price_change_4h,
            "trader_count": trader_count,
            "max_leverage": max_leverage,
            "raw": m,
        }
        xyz_markets.append(entry)
        log(f"Gate 1: xyz:{token} PASS — traders={trader_count}, "
            f"contrib={contribution:.2f}%, vel={velocity_4h:.2f}, "
            f"dir={direction}, maxLev={max_leverage}")

    log(f"Gate 1: {len(xyz_markets)} xyz assets passed.")
    return xyz_markets


# ═══════════════════════════════════════════════════════════════════════════
# Gate 2: Signal Confluence
# ═══════════════════════════════════════════════════════════════════════════

def gate2_signal_confluence(candidates: list, config: dict) -> list:
    """
    Enrich candidates with secondary signals:
    - Tier 2+ momentum events touching xyz assets
    - leaderboard_get_top cross-check for xyz in top traders' markets
    """
    log("Gate 2: Enriching with momentum events and leaderboard top...")

    scanner_cfg = config.get("scanner", {}).get("gate2", {})
    check_momentum = scanner_cfg.get("checkMomentumEvents", True)
    check_top = scanner_cfg.get("checkLeaderboardTop", True)

    # ── Momentum Events ──────────────────────────────────────────────────
    momentum_by_asset = {}
    if check_momentum:
        raw_mom = mcporter_call("leaderboard_get_momentum_events")

        events = []
        if isinstance(raw_mom, dict):
            events = raw_mom.get("events", raw_mom.get("data", []))
        elif isinstance(raw_mom, list):
            events = raw_mom

        for evt in events:
            if not isinstance(evt, dict):
                continue

            tier = safe_int(evt.get("tier", 0))
            if tier < 2:
                continue  # Only Tier 2+ ($5.5M+)

            # Check top_positions for xyz assets
            top_positions = evt.get("top_positions", evt.get("topPositions", []))
            if isinstance(top_positions, list):
                for tp in top_positions:
                    if isinstance(tp, dict):
                        asset_name = str(tp.get("asset", tp.get("coin", tp.get("token", "")))).upper()
                    elif isinstance(tp, str):
                        asset_name = tp.upper()
                    else:
                        continue

                    for c in candidates:
                        if c["token"].upper() == asset_name:
                            tcs = str(evt.get("trader_tags", evt.get("traderTags", {}))
                                      .get("tcs", "") if isinstance(
                                          evt.get("trader_tags", evt.get("traderTags")), dict
                                      ) else "").upper()
                            trp = str(evt.get("trader_tags", evt.get("traderTags", {}))
                                      .get("trp", "") if isinstance(
                                          evt.get("trader_tags", evt.get("traderTags")), dict
                                      ) else "").upper()
                            concentration = safe_float(evt.get("concentration", 0))

                            if asset_name not in momentum_by_asset:
                                momentum_by_asset[asset_name] = []
                            momentum_by_asset[asset_name].append({
                                "tier": tier,
                                "tcs": tcs,
                                "trp": trp,
                                "concentration": concentration,
                            })

    # ── Leaderboard Top Cross-Check ──────────────────────────────────────
    top_trader_xyz = set()
    if check_top:
        raw_top = mcporter_call("leaderboard_get_top")

        traders = []
        if isinstance(raw_top, dict):
            traders = raw_top.get("traders", raw_top.get("data", []))
        elif isinstance(raw_top, list):
            traders = raw_top

        for trader in traders:
            if not isinstance(trader, dict):
                continue
            top_markets = trader.get("top_markets", trader.get("topMarkets", []))
            if isinstance(top_markets, list):
                for mkt in top_markets:
                    name = str(mkt.get("asset", mkt.get("token", mkt)) if isinstance(mkt, dict) else mkt).upper()
                    for c in candidates:
                        if c["token"].upper() == name:
                            top_trader_xyz.add(name)

    # ── Enrich Candidates ────────────────────────────────────────────────
    for c in candidates:
        token_upper = c["token"].upper()
        c["momentum_events"] = momentum_by_asset.get(token_upper, [])
        c["in_top_traders"] = token_upper in top_trader_xyz

        mom_count = len(c["momentum_events"])
        log(f"Gate 2: xyz:{c['token']} — "
            f"momentum_events={mom_count}, "
            f"in_top_traders={c['in_top_traders']}")

    return candidates


# ═══════════════════════════════════════════════════════════════════════════
# Gate 3: Conviction Scoring
# ═══════════════════════════════════════════════════════════════════════════

def gate3_conviction_scoring(candidates: list, config: dict) -> list:
    """
    Score each candidate 0-12:
      SM Concentration (0-3): pct_of_top_traders_gain thresholds
      Trader Count (0-2): count thresholds
      Velocity (0-3): contribution_pct_change_4h magnitude
      Momentum Event (0-2): Tier 2+ presence + quality tags
      Price Momentum (0-2): token_price_change_pct_4h magnitude
    """
    log("Gate 3: Scoring conviction...")

    scanner_cfg = config.get("scanner", {}).get("gate3", {})
    min_score = scanner_cfg.get("minConvictionScore", MIN_CONVICTION_SCORE)

    scored = []
    for c in candidates:
        breakdown = {}

        # ── SM Concentration (0-3) ───────────────────────────────────────
        contrib = c["contribution"]
        if contrib >= 5.0:
            breakdown["sm_concentration"] = 3
        elif contrib >= 2.0:
            breakdown["sm_concentration"] = 2
        elif contrib >= 0.5:
            breakdown["sm_concentration"] = 1
        else:
            breakdown["sm_concentration"] = 0

        # ── Trader Count (0-2) ───────────────────────────────────────────
        tc = c["trader_count"]
        if tc >= 25:
            breakdown["trader_count"] = 2
        elif tc >= 15:
            breakdown["trader_count"] = 1
        else:
            breakdown["trader_count"] = 0

        # ── Velocity (0-3) ───────────────────────────────────────────────
        vel = abs(c["velocity_4h"])
        if vel >= 2.0:
            breakdown["velocity"] = 3
        elif vel >= 1.0:
            breakdown["velocity"] = 2
        elif vel >= 0.3:
            breakdown["velocity"] = 1
        else:
            breakdown["velocity"] = 0

        # ── Momentum Event (0-2) ─────────────────────────────────────────
        events = c.get("momentum_events", [])
        if events:
            # Check for quality tags
            preferred_tcs = {"ELITE", "RELIABLE"}
            preferred_trp = {"SNIPER", "AGGRESSIVE"}
            has_quality = any(
                e.get("tcs") in preferred_tcs and e.get("trp") in preferred_trp
                for e in events
            )
            has_concentration = any(e.get("concentration", 0) > 0.5 for e in events)

            if has_quality or has_concentration:
                breakdown["momentum_event"] = 2
            else:
                breakdown["momentum_event"] = 1
        else:
            breakdown["momentum_event"] = 0

        # ── Price Momentum (0-2) ─────────────────────────────────────────
        price_change = abs(c["price_change_4h"])
        if price_change >= 3.0:
            breakdown["price_momentum"] = 2
        elif price_change >= 1.0:
            breakdown["price_momentum"] = 1
        else:
            breakdown["price_momentum"] = 0

        # ── Total ────────────────────────────────────────────────────────
        score = sum(breakdown.values())
        c["score"] = score
        c["breakdown"] = breakdown

        log(f"Gate 3: xyz:{c['token']} — Score {score}/12 "
            f"(sm={breakdown['sm_concentration']}, "
            f"tc={breakdown['trader_count']}, "
            f"vel={breakdown['velocity']}, "
            f"mom={breakdown['momentum_event']}, "
            f"price={breakdown['price_momentum']})")

        if score < min_score:
            log(f"Gate 3: xyz:{c['token']} — {score} < {min_score}. NO TRADE.")
            continue

        # ── Direction Disagreement Filter ────────────────────────────────
        # If SM direction is long but velocity is sharply negative (or vice versa), skip
        direction = c["direction"]
        raw_velocity = c["velocity_4h"]

        if direction == "long" and raw_velocity < -1.0:
            log(f"Gate 3: xyz:{c['token']} — SM long but velocity={raw_velocity:.2f}. DISAGREE. SKIP.")
            continue
        if direction == "short" and raw_velocity > 1.0:
            log(f"Gate 3: xyz:{c['token']} — SM short but velocity={raw_velocity:.2f}. DISAGREE. SKIP.")
            continue

        scored.append(c)

    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)

    log(f"Gate 3: {len(scored)} candidates scored >= {min_score}.")
    return scored


# ═══════════════════════════════════════════════════════════════════════════
# DSL State Builder (v1.1.1)
# ═══════════════════════════════════════════════════════════════════════════

def build_dsl_state(candidate: dict, config: dict) -> dict:
    """
    Build COMPLETE DSL state from conviction-scored candidate.
    DSL v1.1.1 — scanner generates everything, no dsl-profile.json merging.
    """
    score = candidate["score"]
    direction = candidate["direction"]
    asset = candidate["token"]

    # Find conviction tier
    conv_tiers = config.get("convictionTiers", CONVICTION_TIERS)
    tier = conv_tiers[0]  # default to lowest
    for t in conv_tiers:
        if score >= t["minScore"]:
            tier = t

    timeout = tier["phase1MaxMinutes"]
    weak_peak = tier["weakPeakCutMin"]
    dead_weight = tier["deadWeightCutMin"]
    floor_roe = tier["absoluteFloorRoe"]

    dsl_cfg = config.get("dsl", {})

    state = {
        "active": True,
        "asset": asset,
        "direction": direction,
        "score": score,
        "phase": 1,
        "highWaterPrice": None,
        "highWaterRoe": None,
        "currentTierIndex": -1,
        "consecutiveBreaches": 0,
        "lockMode": dsl_cfg.get("lockMode", "pct_of_high_water"),
        "phase2TriggerRoe": dsl_cfg.get("phase2TriggerRoe", 5),
        "phase1": {
            "enabled": True,
            "retraceThreshold": dsl_cfg.get("phase1RetraceThreshold", 0.03),
            "consecutiveBreachesRequired": 3,
            "phase1MaxMinutes": timeout,
            "weakPeakCutMinutes": weak_peak,
            "deadWeightCutMin": dead_weight,
            "absoluteFloorRoe": floor_roe,
            "weakPeakCut": {
                "enabled": True,
                "intervalInMinutes": weak_peak,
                "minValue": 3.0,
            },
        },
        "phase2": {
            "enabled": True,
            "retraceThreshold": dsl_cfg.get("phase2RetraceThreshold", 0.015),
            "consecutiveBreachesRequired": dsl_cfg.get("phase2ConsecutiveBreaches", 2),
        },
        "tiers": dsl_cfg.get("tiers", DSL_TIERS),
        "stagnationTp": dsl_cfg.get("stagnationTp", STAGNATION_TP),
        "execution": dsl_cfg.get("execution", {
            "phase1SlOrderType": "MARKET",
            "phase2SlOrderType": "MARKET",
            "breachCloseOrderType": "MARKET",
        }),
    }

    return state


# ═══════════════════════════════════════════════════════════════════════════
# Margin / Leverage
# ═══════════════════════════════════════════════════════════════════════════

def get_margin_pct(score: int, config: dict) -> float:
    """Map conviction score to margin percentage of vault."""
    tiers = config.get("sizing", {}).get("marginTiers", MARGIN_TIERS)
    for t in tiers:
        if t["minScore"] <= score <= t["maxScore"]:
            return t["marginPct"]
    return 5.0  # default conservative


def get_leverage(candidate: dict, config: dict) -> float:
    """
    Determine leverage. Uses asset's max_leverage from leaderboard_get_markets,
    capped by skill config. Do NOT hardcode leverage — it varies per XYZ asset.
    """
    cap = config.get("sizing", {}).get("leverageCap", LEVERAGE_CAP)
    asset_max = candidate.get("max_leverage", cap)
    return min(asset_max, cap)


# ═══════════════════════════════════════════════════════════════════════════
# Main Scanner
# ═══════════════════════════════════════════════════════════════════════════

def run():
    log("=" * 60)
    log(f"Scanner run — {datetime.now(timezone.utc).isoformat()}")
    log("=" * 60)

    config = load_config()

    # ── Pre-checks ───────────────────────────────────────────────────────
    # Check max positions
    max_pos = config.get("risk", {}).get("maxPositions", MAX_POSITIONS)
    positions = get_positions()
    xyz_positions = [p for p in positions
                     if str(p.get("coin", p.get("asset", ""))).upper().startswith("XYZ")
                     or str(p.get("coin", p.get("asset", ""))).upper() in _get_known_xyz_tokens()]

    if len(xyz_positions) >= max_pos:
        log(f"Already at max positions ({len(xyz_positions)}/{max_pos}). NO_REPLY.")
        output(no_reply(f"Max positions reached: {len(xyz_positions)}/{max_pos}"))
        return

    # ── Gate 1 ───────────────────────────────────────────────────────────
    xyz_markets = gate1_xyz_universe(config)
    if not xyz_markets:
        output(no_reply("No qualifying xyz assets in leaderboard_get_markets"))
        return

    # ── Cooldown filter ──────────────────────────────────────────────────
    cooldown_min = config.get("risk", {}).get("cooldownMinutes", COOLDOWN_MINUTES)
    pre_cooldown = len(xyz_markets)
    xyz_markets = [m for m in xyz_markets if not is_on_cooldown(m["token"])]
    if len(xyz_markets) < pre_cooldown:
        log(f"Cooldown filtered {pre_cooldown - len(xyz_markets)} assets.")
    if not xyz_markets:
        output(no_reply("All qualifying xyz assets on cooldown"))
        return

    # ── Gate 2 ───────────────────────────────────────────────────────────
    xyz_markets = gate2_signal_confluence(xyz_markets, config)

    # ── Gate 3 ───────────────────────────────────────────────────────────
    scored = gate3_conviction_scoring(xyz_markets, config)
    if not scored:
        output(no_reply("No xyz assets reached conviction threshold"))
        return

    # ── Build Signal ─────────────────────────────────────────────────────
    best = scored[0]
    token = best["token"]
    direction = best["direction"]
    score = best["score"]

    leverage = get_leverage(best, config)
    margin_pct = get_margin_pct(score, config)
    dsl_state = build_dsl_state(best, config)

    log(f"*** SIGNAL: {direction.upper()} xyz:{token} "
        f"(score={score}, lev={leverage}x, margin={margin_pct}%) ***")

    result = {
        "status": "ok",
        "signal": {
            "asset": f"xyz:{token}",
            "direction": direction,
            "score": score,
            "breakdown": best["breakdown"],
            "traderCount": best["trader_count"],
            "contribution": best["contribution"],
            "velocity4h": best["velocity_4h"],
            "priceChange4h": best["price_change_4h"],
            "maxLeverage": best["max_leverage"],
            "momentumEvents": len(best.get("momentum_events", [])),
            "inTopTraders": best.get("in_top_traders", False),
        },
        "entry": {
            "asset": token,
            "direction": direction,
            "leverage": leverage,
            "marginPercent": margin_pct,
        },
        "dslState": dsl_state,
        "constraints": {
            "maxPositions": max_pos,
            "cooldownMinutes": cooldown_min,
            "xyzOnly": True,
        },
    }

    output(result)


def _get_known_xyz_tokens() -> set:
    """
    Known XYZ equity tokens for position matching.
    Positions may show as "SILVER" without xyz: prefix in clearinghouse state.
    """
    return {
        "NVDA", "GOLD", "SILVER", "SKHX", "COPPER",
        "EWY", "NATGAS", "TSLA", "AAPL", "AMZN",
        "GOOGL", "META", "MSFT", "SPY", "QQQ",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        log(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        output({"status": "error", "error": str(e)})
        sys.exit(1)
