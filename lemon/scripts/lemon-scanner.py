#!/usr/bin/env python3
# Senpi LEMON Scanner v1.0
# Copyright 2026 Senpi (https://senpi.ai)
# Licensed under MIT
"""LEMON v1.0 — The Degen Fader.

Find the worst traders on Hyperliquid. Wait until they're bleeding at
high leverage. Take the other side. Ride the liquidation cascade.

Pipeline:
1. discovery_get_top_traders → find DEGEN/CHOPPY traders
2. discovery_get_trader_state → check their live positions
3. Score the vulnerability: leverage × bleeding × cluster × SM × funding
4. If score >= 6 and SM gate passes → enter opposite direction
5. Exit management handled by plugin runtime (runtime.yaml)

Runs every 5 minutes.
"""

import json
import sys
import os
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lemon_config as cfg


# ═══════════════════════════════════════════════════════════════
# HARDCODED CONSTANTS
# ═══════════════════════════════════════════════════════════════

# Target selection
DEGEN_LEVERAGE_THRESHOLD = 10      # Target must be >= 10x leveraged
DEGEN_ROE_THRESHOLD = -10          # Target must be losing >= 10% ROE
TARGET_LIMIT = 10                  # Scan top 10 DEGEN/CHOPPY traders

# Entry
LEVERAGE = 5                       # Conservative — we're the patient predator
MARGIN_PCT = 0.15                  # 15% of account per trade
MAX_POSITIONS = 2
MAX_DAILY_ENTRIES = 4
COOLDOWN_MINUTES = 180             # 3 hours between same-asset entries
MIN_SCORE = 6                      # Minimum conviction score to enter

# SM gate
SM_MIN_TRADERS = 10                # Need 10+ SM traders to confirm
SM_FADE_BLOCK = True               # If SM agrees with degens, don't fade

# Risk
MAX_DAILY_LOSS_PCT = 10
CONSECUTIVE_LOSS_LIMIT = 3
COOLDOWN_ON_LOSSES_MIN = 45
XYZ_BANNED = True


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════════════════════════════════════
# PHASE 1: TARGET ACQUISITION
# ═══════════════════════════════════════════════════════════════

def find_degen_targets():
    """Find DEGEN/CHOPPY traders from the discovery API."""
    result = cfg.mcporter_call("discovery_get_top_traders",
                                time_frame="WEEKLY",
                                activity_labels=["DEGEN"],
                                consistency=["CHOPPY"],
                                limit=TARGET_LIMIT)
    if not result:
        return []

    traders = []
    data = result.get("data", result)
    if isinstance(data, dict):
        trader_list = data.get("traders", data.get("data", []))
    elif isinstance(data, list):
        trader_list = data
    else:
        return []

    for t in trader_list:
        if not isinstance(t, dict):
            continue
        address = t.get("trader_address", t.get("address", t.get("trader_id", "")))
        if address:
            traders.append({
                "address": address,
                "activity": t.get("activity_label", "DEGEN"),
                "consistency": t.get("consistency_label", "CHOPPY"),
                "pnl": safe_float(t.get("total_pnl", t.get("pnl", 0))),
            })

    return traders


# ═══════════════════════════════════════════════════════════════
# PHASE 2: VULNERABILITY SCAN
# ═══════════════════════════════════════════════════════════════

def scan_trader_positions(trader_address):
    """Get a trader's open positions and check for vulnerability."""
    result = cfg.mcporter_call("discovery_get_trader_state",
                                trader_address=trader_address,
                                latest=True)
    if not result:
        return []

    data = result.get("data", result)
    if isinstance(data, dict):
        positions = data.get("openPositions", data.get("positions", []))
    elif isinstance(data, list):
        positions = data
    else:
        return []

    vulnerable = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue

        coin = str(pos.get("coin", pos.get("market", pos.get("asset", "")))).upper()
        if not coin:
            continue

        leverage = safe_float(pos.get("leverage", 0))
        roe = safe_float(pos.get("returnOnEquity", pos.get("roe", pos.get("ROE", 0))))
        direction = str(pos.get("direction", pos.get("side", ""))).upper()
        size = safe_float(pos.get("size", pos.get("szi", 0)))
        entry_price = safe_float(pos.get("entryPrice", pos.get("entryPx", 0)))

        if not direction or direction not in ("LONG", "SHORT"):
            # Try to infer from size
            if size > 0:
                direction = "LONG"
            elif size < 0:
                direction = "SHORT"
            else:
                continue

        # Check vulnerability conditions
        if leverage >= DEGEN_LEVERAGE_THRESHOLD and roe <= DEGEN_ROE_THRESHOLD:
            vulnerable.append({
                "coin": coin,
                "direction": direction,
                "leverage": leverage,
                "roe": roe,
                "size": abs(size),
                "entryPrice": entry_price,
                "traderAddress": trader_address,
            })

    return vulnerable


# ═══════════════════════════════════════════════════════════════
# PHASE 3: CONVICTION SCORING
# ═══════════════════════════════════════════════════════════════

def score_vulnerability(vuln, all_vulns, sm_data):
    """Score a single vulnerability. Returns (score, reasons)."""
    score = 0
    reasons = []
    coin = vuln["coin"]
    degen_direction = vuln["direction"]
    fade_direction = "SHORT" if degen_direction == "LONG" else "LONG"

    # Base: leverage threshold met
    if vuln["leverage"] >= DEGEN_LEVERAGE_THRESHOLD:
        score += 2
        reasons.append(f"DEGEN_{degen_direction} {vuln['leverage']:.0f}x")

    # High leverage bonus
    if vuln["leverage"] >= 20:
        score += 1
        reasons.append(f"HIGH_LEV {vuln['leverage']:.0f}x")

    # Base: bleeding threshold met
    if vuln["roe"] <= DEGEN_ROE_THRESHOLD:
        score += 2
        reasons.append(f"BLEEDING {vuln['roe']:.1f}% ROE")

    # Deep bleeding bonus
    if vuln["roe"] <= -20:
        score += 1
        reasons.append(f"DEEP_BLEED {vuln['roe']:.1f}%")

    # Cluster detection: multiple degens on same coin/direction
    cluster_count = sum(1 for v in all_vulns
                        if v["coin"] == coin and v["direction"] == degen_direction
                        and v["traderAddress"] != vuln["traderAddress"])
    if cluster_count >= 1:
        score += 2
        reasons.append(f"CLUSTER {cluster_count + 1} degens")

    # SM confirmation
    sm_info = get_sm_for_asset(sm_data, coin)
    if sm_info:
        sm_dir = sm_info.get("direction", "").upper()
        sm_traders = sm_info.get("traders", 0)

        if sm_dir == fade_direction and sm_traders >= SM_MIN_TRADERS:
            score += 1
            reasons.append(f"SM_CONFIRMS {fade_direction} ({sm_traders}t)")
        elif sm_dir == degen_direction and sm_traders >= SM_MIN_TRADERS:
            # SM agrees with degens — this is a BLOCK signal
            score -= 3
            reasons.append(f"SM_WITH_DEGENS ({sm_traders}t) — BLOCKED")

    # Funding confirmation
    funding = sm_info.get("funding", 0) if sm_info else 0
    if fade_direction == "LONG" and funding < -0.0001:
        score += 1
        reasons.append(f"FUNDING_CONFIRMS (shorts paying longs)")
    elif fade_direction == "SHORT" and funding > 0.0001:
        score += 1
        reasons.append(f"FUNDING_CONFIRMS (longs paying shorts)")

    return score, reasons, fade_direction


def get_sm_for_asset(sm_data, coin):
    """Extract SM info for a specific asset from leaderboard_get_markets data."""
    for m in sm_data:
        if not isinstance(m, dict):
            continue
        token = str(m.get("token", m.get("asset", ""))).upper()
        dex = str(m.get("dex", "")).lower()
        if token == coin and dex != "xyz":
            return {
                "direction": str(m.get("direction", "")).upper(),
                "traders": int(m.get("trader_count", 0)),
                "pct": safe_float(m.get("pct_of_top_traders_gain", 0)),
                "funding": safe_float(m.get("funding", m.get("fundingRate", 0))),
            }
    return None



# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def run():
    wallet, strategy_id = cfg.get_wallet_and_strategy()
    if not wallet:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY", "note": "no wallet"})
        return

    # ── Check existing positions (NO thesis exit) ─────────────
    account_value, positions = cfg.get_positions(wallet)
    if account_value <= 0:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY", "note": "cannot read account"})
        return

    if len(positions) >= MAX_POSITIONS:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                     "note": f"{len(positions)} positions active."})
        return

    # ── Trade counter / circuit breaker ───────────────────────
    tc = cfg.load_trade_counter()

    if tc.get("gate") == "PAUSED":
        pause_until = tc.get("pauseUntil", 0)
        if cfg.now_ts() < pause_until:
            cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                        "note": f"Paused: {(pause_until - cfg.now_ts())/60:.0f}min"})
            return
        tc["gate"] = "OPEN"

    if tc.get("entries", 0) >= MAX_DAILY_ENTRIES:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                    "note": f"Daily entry limit ({MAX_DAILY_ENTRIES}) reached"})
        return

    if tc.get("consecutiveLosses", 0) >= CONSECUTIVE_LOSS_LIMIT:
        tc["gate"] = "PAUSED"
        tc["pauseUntil"] = cfg.now_ts() + (COOLDOWN_ON_LOSSES_MIN * 60)
        cfg.save_trade_counter(tc)
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                    "note": f"{CONSECUTIVE_LOSS_LIMIT} consecutive losses → {COOLDOWN_ON_LOSSES_MIN}min cooldown"})
        return

    # ── Phase 1: Find DEGEN/CHOPPY targets ────────────────────
    cfg.log("Scanning for DEGEN/CHOPPY targets...")
    targets = find_degen_targets()

    if not targets:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                    "note": "No DEGEN/CHOPPY traders found"})
        return

    cfg.log(f"Found {len(targets)} DEGEN/CHOPPY targets")

    # ── Phase 2: Scan each target's positions for vulnerability ──
    all_vulnerabilities = []
    for target in targets:
        vulns = scan_trader_positions(target["address"])
        for v in vulns:
            # Skip xyz assets
            if XYZ_BANNED and v["coin"].lower().startswith("xyz"):
                continue
            all_vulnerabilities.append(v)

    if not all_vulnerabilities:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                    "note": f"Scanned {len(targets)} degens — none vulnerable "
                            f"(need {DEGEN_LEVERAGE_THRESHOLD}x+ lev AND {DEGEN_ROE_THRESHOLD}%+ ROE)"})
        return

    cfg.log(f"Found {len(all_vulnerabilities)} vulnerable positions across {len(targets)} degens")

    # ── Fetch SM data for scoring ─────────────────────────────
    raw_sm = cfg.mcporter_call("leaderboard_get_markets")
    sm_data = []
    if raw_sm:
        if isinstance(raw_sm, dict):
            sm_data = raw_sm.get("markets", raw_sm.get("data", []))
        elif isinstance(raw_sm, list):
            sm_data = raw_sm

    # ── Phase 3: Score and rank vulnerabilities ───────────────
    scored = []
    seen_coins = set()  # Max 1 fade per coin (cluster = 1 signal)

    for vuln in all_vulnerabilities:
        coin = vuln["coin"]
        if coin in seen_coins:
            continue

        # Skip if on cooldown
        if cfg.is_on_cooldown(coin):
            continue

        # Skip if already have this coin
        if any(p["coin"].upper() == coin.upper() for p in positions):
            continue

        score, reasons, fade_direction = score_vulnerability(vuln, all_vulnerabilities, sm_data)

        if score >= MIN_SCORE:
            seen_coins.add(coin)
            scored.append({
                "coin": coin,
                "fadeDirection": fade_direction,
                "score": score,
                "reasons": reasons,
                "targetLeverage": vuln["leverage"],
                "targetRoe": vuln["roe"],
                "targetDirection": vuln["direction"],
                "targetAddress": vuln["traderAddress"],
                "clusterSize": sum(1 for v in all_vulnerabilities if v["coin"] == coin),
            })

    # Sort by score descending
    scored.sort(key=lambda s: s["score"], reverse=True)

    if not scored:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                    "note": f"{len(all_vulnerabilities)} vulnerable degens found, "
                            f"but none scored >= {MIN_SCORE}"})

        # Save scan history for cluster detection
        history = cfg.load_scan_history()
        history["scans"].append({
            "timestamp": cfg.now_iso(),
            "targets": len(targets),
            "vulnerabilities": len(all_vulnerabilities),
            "scored": 0,
        })
        cfg.save_scan_history(history)
        return

    # ── Take the best signal ──────────────────────────────────
    best = scored[0]
    margin = round(account_value * MARGIN_PCT, 2)

    tc["entries"] = tc.get("entries", 0) + 1
    cfg.save_trade_counter(tc)

    # Save scan history
    history = cfg.load_scan_history()
    history["scans"].append({
        "timestamp": cfg.now_iso(),
        "targets": len(targets),
        "vulnerabilities": len(all_vulnerabilities),
        "scored": len(scored),
        "entered": best["coin"],
    })
    cfg.save_scan_history(history)

    cfg.output({
        "status": "ok",
        "signal": {
            "asset": best["coin"],
            "direction": best["fadeDirection"],
            "score": best["score"],
            "mode": "DEGEN_FADE",
            "reasons": best["reasons"],
            "target": {
                "address": best["targetAddress"][:10] + "...",
                "direction": best["targetDirection"],
                "leverage": best["targetLeverage"],
                "roe": best["targetRoe"],
                "clusterSize": best["clusterSize"],
            },
        },
        "entry": {
            "asset": best["coin"],
            "direction": best["fadeDirection"],
            "leverage": LEVERAGE,
            "margin": margin,
            "orderType": "FEE_OPTIMIZED_LIMIT",
        },
        "constraints": {
            "maxPositions": MAX_POSITIONS,
            "maxLeverage": LEVERAGE,
            "maxDailyEntries": MAX_DAILY_ENTRIES,
            "cooldownMinutes": COOLDOWN_MINUTES,
            "xyzBanned": XYZ_BANNED,
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
