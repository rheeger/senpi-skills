#!/usr/bin/env python3
# Senpi ORCA Scanner v1.3
# Copyright 2026 Senpi (https://senpi.ai)
# Licensed under MIT
"""ORCA v1.3 — Dual-Mode Scanner (Stalker + Striker).

The clean A/B experiment: does Stalker add value on top of Striker?

Roach = Striker only (+8.2%).
Orca v1.3 = Stalker + Striker with hardened infrastructure.
If v1.3 beats Roach, Stalker has value. If Roach still wins, Stalker dies.

v1.2 had broken infrastructure (crons dying, state files in wrong dirs,
self-healing loops that made things worse). v1.3 fixes all of that:
- DSL state includes wallet, strategyWalletAddress, strategyId, size placeholder
- No thesis exit (scanner does NOT re-evaluate open positions)
- No Hunter mode (0 trades across all testing)
- No pyramiding (never triggered, adds complexity)
- Max 8 entries/day (v1.1 was doing 30/day and bleeding $80+/day in fees)
- Leverage reduced to 7x
- Per-asset cooldown 120 min

Runs every 3 minutes.
"""

import json
import sys
import os
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import orca_config as cfg


# ═══════════════════════════════════════════════════════════════
# HARDCODED CONSTANTS
# ═══════════════════════════════════════════════════════════════

MIN_LEVERAGE = 5
MAX_LEVERAGE = 7                    # Reduced from 10x
DEFAULT_LEVERAGE = 7
MAX_POSITIONS = 3
MAX_DAILY_ENTRIES = 8               # Prevents fee bleed ($32/day max at ~$4/trade)
COOLDOWN_MINUTES = 120
MAX_DAILY_LOSS_PCT = 10
XYZ_BANNED = True

# Stalker thresholds
STALKER_MIN_SCORE = 7               # Floor — config can raise but never lower
STALKER_MIN_CONSECUTIVE_SCANS = 3
STALKER_MIN_TOTAL_CLIMB = 8
STALKER_MOMENTUM_GATE_SCORE = 9     # Below 9, need momentum event confirmation

# Striker thresholds
STRIKER_MIN_SCORE = 9
STRIKER_MIN_REASONS = 4
STRIKER_MIN_RANK_JUMP = 15
STRIKER_MIN_PREV_RANK = 25
STRIKER_MIN_VOLUME_RATIO = 1.5

# DSL v1.1.1 conviction tiers
CONVICTION_TIERS = [
    {"minScore": 6, "absoluteFloorRoe": -18, "hardTimeoutMin": 25,
     "weakPeakCutMin": 12, "deadWeightCutMin": 8},
    {"minScore": 8, "absoluteFloorRoe": -25, "hardTimeoutMin": 45,
     "weakPeakCutMin": 20, "deadWeightCutMin": 15},
    {"minScore": 10, "absoluteFloorRoe": -30, "hardTimeoutMin": 60,
     "weakPeakCutMin": 30, "deadWeightCutMin": 20},
]

DSL_TIERS = [
    {"triggerPct": 7, "lockHwPct": 40, "consecutiveBreachesRequired": 3},
    {"triggerPct": 12, "lockHwPct": 55, "consecutiveBreachesRequired": 2},
    {"triggerPct": 15, "lockHwPct": 75, "consecutiveBreachesRequired": 2},
    {"triggerPct": 20, "lockHwPct": 85, "consecutiveBreachesRequired": 1},
]

STAGNATION_TP = {"enabled": True, "roeMin": 10, "hwStaleMin": 45}


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def now_date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def check_4h_alignment(direction, price_chg_4h):
    if direction == "LONG" and price_chg_4h > 0:
        return True
    if direction == "SHORT" and price_chg_4h < 0:
        return True
    return False


def get_market_in_scan(scan, token, dex):
    for m in scan.get("markets", []):
        if m.get("token") == token and m.get("dex", "") == dex:
            return m
    return None


# ═══════════════════════════════════════════════════════════════
# SCAN DATA FETCHING
# ═══════════════════════════════════════════════════════════════

def fetch_markets():
    raw = cfg.mcporter_call("leaderboard_get_markets")
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw.get("markets", raw.get("data", []))
    elif isinstance(raw, list):
        return raw
    return None


def build_scan_snapshot(markets_data):
    markets = []
    for m in markets_data:
        if not isinstance(m, dict):
            continue
        dex = m.get("dex", "")
        if XYZ_BANNED and dex == "xyz":
            continue
        markets.append({
            "token": str(m.get("token", m.get("asset", ""))).upper(),
            "dex": dex,
            "rank": int(m.get("rank", m.get("position", 999))),
            "direction": str(m.get("direction", "")).upper(),
            "contribution": safe_float(m.get("pct_of_top_traders_gain", 0)),
            "traders": int(m.get("trader_count", 0)),
            "price_chg_4h": safe_float(m.get("token_price_change_pct_4h", 0)),
            "price_chg_1h": safe_float(m.get("token_price_change_pct_1h",
                                       m.get("price_change_1h", 0))),
            "volume": safe_float(m.get("volume", 0)),
            "avg_volume": safe_float(m.get("avg_volume_6h", m.get("avgVolume", 0))),
        })
    return {"markets": markets, "timestamp": now_iso()}


# ═══════════════════════════════════════════════════════════════
# MODE A: STALKER (Accumulation Detection)
# ═══════════════════════════════════════════════════════════════

def detect_stalker_signals(current_scan, history):
    """Detect steady rank climbers over 3+ consecutive scans.
    Score 7+ required. Below score 9, needs momentum event backing."""

    prev_scans = history.get("scans", [])
    if len(prev_scans) < STALKER_MIN_CONSECUTIVE_SCANS:
        return []

    signals = []

    for market in current_scan.get("markets", []):
        token = market.get("token", "")
        dex = market.get("dex", "")
        current_rank = market.get("rank", 999)
        direction = market.get("direction", "").upper()

        if current_rank <= 10:
            continue

        if not check_4h_alignment(direction, market.get("price_chg_4h", 0)):
            continue

        # Build rank history
        rank_history = []
        contrib_history = []
        for scan in prev_scans[-(STALKER_MIN_CONSECUTIVE_SCANS + 2):]:
            m = get_market_in_scan(scan, token, dex)
            if m:
                rank_history.append(m.get("rank", 999))
                contrib_history.append(m.get("contribution", 0))
            else:
                rank_history.append(None)
                contrib_history.append(None)
        rank_history.append(current_rank)
        contrib_history.append(market.get("contribution", 0))

        valid_ranks = [(i, r) for i, r in enumerate(rank_history) if r is not None]
        if len(valid_ranks) < STALKER_MIN_CONSECUTIVE_SCANS + 1:
            continue

        recent_ranks = [r for _, r in valid_ranks[-(STALKER_MIN_CONSECUTIVE_SCANS + 1):]]
        is_climbing = all(recent_ranks[i] >= recent_ranks[i + 1]
                          for i in range(len(recent_ranks) - 1))
        total_climb = recent_ranks[0] - recent_ranks[-1]

        if not is_climbing or total_climb < STALKER_MIN_TOTAL_CLIMB:
            continue

        # Contribution building check
        valid_contribs = [c for c in contrib_history if c is not None]
        if len(valid_contribs) >= 3:
            recent_c = valid_contribs[-3:]
            volume_building = all(recent_c[i] <= recent_c[i + 1]
                                  for i in range(len(recent_c) - 1))
            if not volume_building:
                continue

        # ── Scoring ──
        score = 0
        reasons = []

        score += 3
        reasons.append(f"STALKER_CLIMB +{total_climb} over {len(recent_ranks)} scans")

        if len(valid_contribs) >= 2:
            deltas = [valid_contribs[i + 1] - valid_contribs[i]
                      for i in range(len(valid_contribs) - 1)]
            vel = sum(deltas) / len(deltas)
            if vel > 0.001:
                score += 2
                reasons.append(f"CONTRIB_ACCEL +{vel * 100:.3f}%/scan")
            elif vel > 0:
                score += 1
                reasons.append(f"CONTRIB_POSITIVE +{vel * 100:.4f}%/scan")

        if market.get("traders", 0) >= 10:
            score += 1
            reasons.append(f"SM_ACTIVE {market['traders']} traders")

        if recent_ranks[0] >= 30:
            score += 1
            reasons.append(f"DEEP_START from #{recent_ranks[0]}")

        # 4H strength bonus
        p4h = abs(market.get("price_chg_4h", 0))
        if p4h > 3:
            score += 1
            reasons.append(f"STRONG_4H {market['price_chg_4h']:+.1f}%")

        if score < STALKER_MIN_SCORE:
            continue

        # Momentum gate: score 7-8 Stalkers without momentum backing
        # are catching chop, not accumulation. Fox data: 17.6% WR at score 6-7.
        if score < STALKER_MOMENTUM_GATE_SCORE:
            # For v1.3, we require 4H > 1% aligned and traders > 15 as proxy
            p4h_aligned = (direction == "LONG" and market.get("price_chg_4h", 0) > 1.0) or \
                          (direction == "SHORT" and market.get("price_chg_4h", 0) < -1.0)
            deep_sm = market.get("traders", 0) >= 15
            if not (p4h_aligned and deep_sm):
                continue

        signals.append({
            "token": token,
            "dex": dex if dex else None,
            "direction": direction,
            "mode": "STALKER",
            "score": score,
            "reasons": reasons,
            "currentRank": current_rank,
            "totalClimb": total_climb,
            "traders": market.get("traders", 0),
            "priceChg4h": market.get("price_chg_4h", 0),
        })

    return signals


# ═══════════════════════════════════════════════════════════════
# MODE B: STRIKER (Explosion Detection)
# ═══════════════════════════════════════════════════════════════

def detect_striker_signals(current_scan, history):
    """Detect violent FIRST_JUMP signals. Same logic as Roach."""

    prev_scans = history.get("scans", [])
    if not prev_scans:
        return []

    latest_prev = prev_scans[-1]
    prev_top50_tokens = set()
    for m in latest_prev.get("markets", []):
        prev_top50_tokens.add((m.get("token", ""), m.get("dex", "")))

    signals = []

    for market in current_scan.get("markets", []):
        token = market.get("token", "")
        dex = market.get("dex", "")
        current_rank = market.get("rank", 999)
        direction = market.get("direction", "").upper()
        current_contrib = market.get("contribution", 0)
        traders = market.get("traders", 0)

        if current_rank <= 10:
            continue
        if not check_4h_alignment(direction, market.get("price_chg_4h", 0)):
            continue

        prev_market = get_market_in_scan(latest_prev, token, dex)
        if not prev_market:
            continue

        rank_jump = prev_market.get("rank", 999) - current_rank
        prev_rank = prev_market.get("rank", 999)

        is_first_jump = False
        is_immediate = False
        reasons = []

        if rank_jump >= 10 and prev_rank >= STRIKER_MIN_PREV_RANK:
            is_immediate = True
            reasons.append(f"IMMEDIATE_MOVER +{rank_jump} from #{prev_rank}")
            was_in_prev = (token, dex) in prev_top50_tokens
            if not was_in_prev or prev_rank >= 30:
                is_first_jump = True
                reasons.append(f"FIRST_JUMP #{prev_rank}->#{current_rank}")

        if not is_first_jump and not is_immediate:
            continue
        if rank_jump < STRIKER_MIN_RANK_JUMP:
            continue

        # Contribution explosion
        if prev_market.get("contribution", 0) > 0:
            contrib_ratio = current_contrib / prev_market["contribution"]
            if contrib_ratio >= 3.0:
                reasons.append(f"CONTRIB_EXPLOSION {contrib_ratio:.1f}x")

        # Contribution velocity
        contrib_velocity = 0
        recent_contribs = []
        for scan in prev_scans[-5:]:
            m = get_market_in_scan(scan, token, dex)
            if m:
                recent_contribs.append(m.get("contribution", 0))
        recent_contribs.append(current_contrib)
        if len(recent_contribs) >= 2:
            deltas = [recent_contribs[i + 1] - recent_contribs[i]
                      for i in range(len(recent_contribs) - 1)]
            contrib_velocity = sum(deltas) / len(deltas) * 100

        # ── Scoring ──
        score = 0
        if is_first_jump:
            score += 3
        if is_immediate:
            score += 2
        if abs(contrib_velocity) > 10:
            score += 2
            reasons.append(f"HIGH_VELOCITY {abs(contrib_velocity):.1f}")
        if prev_rank >= 40:
            score += 1
            reasons.append("DEEP_CLIMBER")
        if abs(market.get("price_chg_4h", 0)) > 3:
            score += 1
            reasons.append(f"STRONG_4H {market['price_chg_4h']:+.1f}%")
        if traders >= 30:
            score += 1
            reasons.append(f"DEEP_SM ({traders}t)")

        if score < STRIKER_MIN_SCORE or len(reasons) < STRIKER_MIN_REASONS:
            continue

        # Volume confirmation
        vol_ratio = 0
        volume = safe_float(market.get("volume", 0))
        avg_volume = safe_float(market.get("avg_volume", 0))
        if avg_volume > 0:
            vol_ratio = volume / avg_volume
        if vol_ratio < STRIKER_MIN_VOLUME_RATIO:
            continue
        reasons.append(f"VOL {vol_ratio:.1f}x")

        signals.append({
            "token": token,
            "dex": dex if dex else None,
            "direction": direction,
            "mode": "STRIKER",
            "score": score,
            "reasons": reasons,
            "currentRank": current_rank,
            "rankJump": rank_jump,
            "isFirstJump": is_first_jump,
            "contribVelocity": round(contrib_velocity, 4),
            "volRatio": round(vol_ratio, 2),
            "traders": traders,
            "priceChg4h": market.get("price_chg_4h", 0),
        })

    signals.sort(key=lambda s: s["score"], reverse=True)
    return signals


# ═══════════════════════════════════════════════════════════════
# DSL STATE BUILDER (v1.1.1 — conviction-tiered)
# ═══════════════════════════════════════════════════════════════

def build_dsl_state(signal, wallet, strategy_id):
    """Build complete DSL state with conviction-based Phase 1 settings."""
    score = signal.get("score", 6)

    tier = CONVICTION_TIERS[0]
    for ct in CONVICTION_TIERS:
        if score >= ct["minScore"]:
            tier = ct

    return {
        "active": True,
        "asset": signal.get("token", ""),
        "direction": signal.get("direction", ""),
        "mode": signal.get("mode", "STALKER"),
        "score": score,
        "phase": 1,
        "highWaterPrice": None,
        "highWaterRoe": None,
        "currentTierIndex": -1,
        "consecutiveBreaches": 0,
        "wallet": wallet,
        "strategyWalletAddress": wallet,
        "strategyId": strategy_id,
        "size": None,  # Agent MUST set from clearinghouse after entry
        "lockMode": "pct_of_high_water",
        "phase2TriggerRoe": 7,
        "phase1": {
            "enabled": True,
            "retraceThreshold": 0.03,
            "consecutiveBreachesRequired": 3,
            "phase1MaxMinutes": tier["hardTimeoutMin"],
            "weakPeakCutMinutes": tier["weakPeakCutMin"],
            "deadWeightCutMin": tier["deadWeightCutMin"],
            "absoluteFloorRoe": tier["absoluteFloorRoe"],
            "weakPeakCut": {
                "enabled": True,
                "intervalInMinutes": tier["weakPeakCutMin"],
                "minValue": 3.0,
            },
        },
        "tiers": DSL_TIERS,
        "stagnationTp": STAGNATION_TP,
        "execution": {
            "phase1SlOrderType": "MARKET",
            "phase2SlOrderType": "MARKET",
            "breachCloseOrderType": "MARKET",
        },
        "_v2_no_thesis_exit": True,
        "_orca_version": "1.3",
        "_note": "DSL manages ALL exits. Scanner does NOT re-evaluate open positions. "
                 "Agent MUST set 'size' from clearinghouse after entry.",
    }


# ═══════════════════════════════════════════════════════════════
# SCAN HISTORY
# ═══════════════════════════════════════════════════════════════

def load_scan_history():
    p = os.path.join(cfg.STATE_DIR, "scan-history.json")
    if os.path.exists(p):
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
    cfg.atomic_write(os.path.join(cfg.STATE_DIR, "scan-history.json"), history)


# ═══════════════════════════════════════════════════════════════
# TRADE COUNTER & COOLDOWN
# ═══════════════════════════════════════════════════════════════

def load_trade_counter():
    p = os.path.join(cfg.STATE_DIR, "trade-counter.json")
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"date": now_date(), "entries": 0}


def save_trade_counter(tc):
    if tc.get("date") != now_date():
        tc = {"date": now_date(), "entries": 0}
    cfg.atomic_write(os.path.join(cfg.STATE_DIR, "trade-counter.json"), tc)


def is_on_cooldown(coin):
    p = os.path.join(cfg.STATE_DIR, "cooldowns.json")
    if not os.path.exists(p):
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
                    "note": f"{len(positions)} positions active. DSL manages exit.",
                    "_v2_no_thesis_exit": True})
        return

    # ── Trade counter ─────────────────────────────────────────
    tc = load_trade_counter()
    if tc.get("entries", 0) >= MAX_DAILY_ENTRIES:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                    "note": f"Daily entry limit ({MAX_DAILY_ENTRIES}) reached"})
        return

    # ── Fetch SM data ─────────────────────────────────────────
    raw_markets = fetch_markets()
    if raw_markets is None:
        cfg.output({"status": "error", "error": "failed to fetch markets"})
        return

    # ── Build scan snapshot ───────────────────────────────────
    current_scan = build_scan_snapshot(raw_markets)
    history = load_scan_history()
    history["scans"].append(current_scan)
    save_scan_history(history)

    if len(history["scans"]) < 2:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                    "note": "Building scan history"})
        return

    # ── Detect signals (both modes) ───────────────────────────
    stalker_signals = detect_stalker_signals(current_scan, history)
    striker_signals = detect_striker_signals(current_scan, history)

    # ── Combine: Striker priority, then Stalker ───────────────
    seen_tokens = set()
    combined = []
    for sig in striker_signals:
        seen_tokens.add(sig["token"])
        combined.append(sig)
    for sig in stalker_signals:
        if sig["token"] not in seen_tokens:
            seen_tokens.add(sig["token"])
            combined.append(sig)
    combined.sort(key=lambda s: s["score"], reverse=True)

    # ── Apply filters ─────────────────────────────────────────
    available_slots = MAX_POSITIONS - len(positions)
    filtered = []
    for sig in combined:
        if len(filtered) >= available_slots:
            break
        if is_on_cooldown(sig["token"]):
            continue
        if any(p["coin"].upper() == sig["token"].upper() for p in positions):
            continue
        filtered.append(sig)

    if not filtered:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                    "note": f"No signals. Scanned {len(current_scan['markets'])} markets. "
                            f"Stalker: {len(stalker_signals)}, Striker: {len(striker_signals)}"})
        return

    # ── Build output with DSL state ───────────────────────────
    for sig in filtered:
        sig["dslState"] = build_dsl_state(sig, wallet, strategy_id)

    tc["entries"] = tc.get("entries", 0) + len(filtered)
    save_trade_counter(tc)

    # Truncate to available slots
    filtered = filtered[:available_slots]

    margin_per = round(account_value * 0.20, 2)

    cfg.output({
        "status": "ok",
        "totalMarkets": len(current_scan["markets"]),
        "stalkerCount": len(stalker_signals),
        "strikerCount": len(striker_signals),
        "combined": [{
            "signal": {
                "asset": s["token"],
                "direction": s["direction"],
                "score": s["score"],
                "mode": s["mode"],
                "reasons": s["reasons"],
            },
            "entry": {
                "asset": s["token"],
                "direction": s["direction"],
                "leverage": DEFAULT_LEVERAGE,
                "margin": margin_per,
                "orderType": "FEE_OPTIMIZED_LIMIT",
            },
            "dslState": s["dslState"],
        } for s in filtered],
        "constraints": {
            "maxPositions": MAX_POSITIONS,
            "maxLeverage": MAX_LEVERAGE,
            "maxDailyEntries": MAX_DAILY_ENTRIES,
            "cooldownMinutes": COOLDOWN_MINUTES,
            "xyzBanned": XYZ_BANNED,
            "scoreFloors": {
                "stalker": STALKER_MIN_SCORE,
                "striker": STRIKER_MIN_SCORE,
            },
            "_v2_no_thesis_exit": True,
            "_note": "DSL manages ALL exits. Agent MUST set dslState.size from clearinghouse after entry.",
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
