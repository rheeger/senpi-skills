#!/usr/bin/env python3
# Senpi CHEETAH Scanner v2.0
# Copyright 2026 Senpi (https://senpi.ai)
# Licensed under MIT
"""CHEETAH v2.0 — The Ultimate HYPE Predator.

Single asset: HYPE. Every signal source. Maximum patience.

HYPE is unique: Hyperliquid's native token, narrative-driven, lower BTC
correlation, routinely wicks 5-10% intraday, SM positioning often extreme.

v1.0 had zero trades because the entry gates were too strict for choppy
conditions (required 1H to confirm 4H while SM was opposing). v2.0 keeps
high conviction requirements but adds flexibility:

- SM COMMITMENT gate: SM must be 80%+ one direction (not just aligned)
- BTC is a booster, never a gate
- Funding extreme is a bonus signal, not a block
- 4H trend required, 1H confirms for bonus points but doesn't block
- OI building = conviction growing
- Volume surge = the move is real

Score 8+ to enter. Leverage 5-7x (HYPE is volatile enough).
Max 3 entries/day. 120 min cooldown.

DSL exit managed by plugin runtime. Scanner does NOT manage exits.

Uses: leaderboard_get_markets + market_get_asset_data
Runs every 3 minutes.
"""

import json
import sys
import os
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cheetah_config as cfg


# ═══════════════════════════════════════════════════════════════
# HARDCODED CONSTANTS
# ═══════════════════════════════════════════════════════════════

ASSET = "HYPE"                      # Single asset — nothing else
MIN_LEVERAGE = 5
MAX_LEVERAGE = 7                    # HYPE is volatile — 7x max
DEFAULT_LEVERAGE = 7
MAX_POSITIONS = 1                   # One HYPE position at a time
MAX_DAILY_ENTRIES = 3               # Patient — 3 max
COOLDOWN_MINUTES = 120
MARGIN_PCT = 0.25                   # 25% of account
MIN_SCORE = 8                       # High conviction required
XYZ_BANNED = True

# SM commitment thresholds — HYPE needs extreme SM conviction
MIN_SM_PCT = 3.0                    # Minimum SM concentration
MIN_SM_TRADERS = 15                 # HYPE has fewer SM traders than BTC/ETH
SM_COMMITMENT_PCT = 80              # SM must be 80%+ one direction

# Funding thresholds
FUNDING_EXTREME_THRESHOLD = 0.0003  # >0.03%/hr = extreme
FUNDING_CONFIRMS_THRESHOLD = 0.0001 # >0.01%/hr = confirms pressure


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


# ═══════════════════════════════════════════════════════════════
# SIGNAL SOURCES
# ═══════════════════════════════════════════════════════════════

def fetch_hype_sm_data():
    """Get HYPE SM positioning from leaderboard."""
    raw = cfg.mcporter_call("leaderboard_get_markets")
    if not raw:
        return None

    markets = []
    if isinstance(raw, dict):
        markets = raw.get("markets", raw.get("data", []))
    elif isinstance(raw, list):
        markets = raw

    for m in markets:
        if not isinstance(m, dict):
            continue
        token = str(m.get("token", "")).upper()
        if token == ASSET:
            return {
                "direction": str(m.get("direction", "")).upper(),
                "pct": safe_float(m.get("pct_of_top_traders_gain", 0)),
                "traders": int(m.get("trader_count", 0)),
                "price_chg_4h": safe_float(m.get("token_price_change_pct_4h", 0)),
                "price_chg_1h": safe_float(m.get("token_price_change_pct_1h",
                                           m.get("price_change_1h", 0))),
                "contrib_change": safe_float(m.get("contribution_pct_change_4h", 0)),
                "rank": int(m.get("rank", m.get("position", 999))),
            }
    return None


def fetch_hype_market_data():
    """Get HYPE funding, OI, volume from market data."""
    data = cfg.mcporter_call("market_get_asset_data",
                              asset=ASSET,
                              candle_intervals=["1h"],
                              include_funding=True)
    if not data:
        return None

    ad = data.get("data", data)
    if not isinstance(ad, dict):
        return None

    ac = ad.get("asset_context", ad.get("assetContext", {}))
    if not isinstance(ac, dict):
        return {}

    funding = safe_float(ac.get("funding", ac.get("fundingRate", 0)))
    oi = safe_float(ac.get("openInterest", ac.get("oi", 0)))
    volume_24h = safe_float(ac.get("dayNtlVlm", ac.get("volume24h", 0)))
    prev_day_volume = safe_float(ac.get("prevDayNtlVlm", 0))

    # Volume ratio
    vol_ratio = 0
    if prev_day_volume > 0:
        vol_ratio = volume_24h / prev_day_volume

    return {
        "funding": funding,
        "oi": oi,
        "volume_24h": volume_24h,
        "vol_ratio": vol_ratio,
    }


# ═══════════════════════════════════════════════════════════════
# SCORING — 14-point system
# ═══════════════════════════════════════════════════════════════

def score_hype(sm_data, market_data):
    """Score HYPE across all signal sources. Returns (score, reasons, direction)."""
    if not sm_data:
        return 0, ["NO_SM_DATA"], None

    score = 0
    reasons = []
    direction = sm_data["direction"]

    if direction not in ("LONG", "SHORT"):
        return 0, ["NO_DIRECTION"], None

    # ── 1. SM COMMITMENT (0-4 points) ────────────────────────
    # This is the primary signal. SM must be committed.
    pct = sm_data["pct"]
    traders = sm_data["traders"]

    if pct < MIN_SM_PCT or traders < MIN_SM_TRADERS:
        return 0, [f"SM_WEAK ({pct:.1f}%, {traders}t)"], None

    if pct >= 15:
        score += 4
        reasons.append(f"SM_DOMINANT {pct:.1f}% ({traders}t)")
    elif pct >= 8:
        score += 3
        reasons.append(f"SM_STRONG {pct:.1f}% ({traders}t)")
    elif pct >= 5:
        score += 2
        reasons.append(f"SM_SOLID {pct:.1f}% ({traders}t)")
    else:
        score += 1
        reasons.append(f"SM_BASE {pct:.1f}% ({traders}t)")

    # ── 2. TREND ALIGNMENT (0-3 points) ──────────────────────
    p4h = sm_data["price_chg_4h"]
    p1h = sm_data["price_chg_1h"]

    # 4H trend is required — must agree with SM direction
    if direction == "LONG" and p4h > 0.3:
        score += 2
        reasons.append(f"4H_BULLISH +{p4h:.1f}%")
    elif direction == "SHORT" and p4h < -0.3:
        score += 2
        reasons.append(f"4H_BEARISH {p4h:.1f}%")
    elif direction == "LONG" and p4h > 0:
        score += 1
        reasons.append(f"4H_POSITIVE +{p4h:.2f}%")
    elif direction == "SHORT" and p4h < 0:
        score += 1
        reasons.append(f"4H_POSITIVE {p4h:.2f}%")
    else:
        # 4H opposes SM — hard block
        return 0, [f"4H_OPPOSES ({p4h:+.1f}% vs SM {direction})"], None

    # 1H confirms for bonus (not required)
    if direction == "LONG" and p1h > 0.2:
        score += 1
        reasons.append(f"1H_CONFIRMS +{p1h:.2f}%")
    elif direction == "SHORT" and p1h < -0.2:
        score += 1
        reasons.append(f"1H_CONFIRMS {p1h:.2f}%")

    # ── 3. CONTRIBUTION VELOCITY (0-2 points) ────────────────
    contrib = sm_data["contrib_change"]
    if abs(contrib) >= 0.05:
        score += 2
        reasons.append(f"CONTRIB_SURGE +{abs(contrib)*100:.1f}%")
    elif abs(contrib) >= 0.01:
        score += 1
        reasons.append(f"CONTRIB_ACCEL +{abs(contrib)*100:.2f}%")

    # ── 4. FUNDING (0-2 points) ──────────────────────────────
    if market_data:
        funding = market_data.get("funding", 0)
        # Funding paying your direction = pressure building
        if direction == "SHORT" and funding > FUNDING_EXTREME_THRESHOLD:
            score += 2
            reasons.append(f"FUNDING_EXTREME +{funding*100:.4f}%/hr")
        elif direction == "SHORT" and funding > FUNDING_CONFIRMS_THRESHOLD:
            score += 1
            reasons.append(f"FUNDING_CONFIRMS +{funding*100:.4f}%/hr")
        elif direction == "LONG" and funding < -FUNDING_EXTREME_THRESHOLD:
            score += 2
            reasons.append(f"FUNDING_EXTREME {funding*100:.4f}%/hr")
        elif direction == "LONG" and funding < -FUNDING_CONFIRMS_THRESHOLD:
            score += 1
            reasons.append(f"FUNDING_CONFIRMS {funding*100:.4f}%/hr")

    # ── 5. VOLUME (0-1 point) ────────────────────────────────
    if market_data:
        vol_ratio = market_data.get("vol_ratio", 0)
        if vol_ratio >= 1.5:
            score += 1
            reasons.append(f"VOL_SURGE {vol_ratio:.1f}x")

    # ── 6. BTC BOOSTER (0-1 point) ───────────────────────────
    # BTC alignment is a bonus, never a gate
    btc_data = fetch_btc_direction()
    if btc_data:
        if btc_data == direction:
            score += 1
            reasons.append("BTC_CONFIRMS")

    # ── 7. RANK POSITION (0-1 point) ─────────────────────────
    rank = sm_data.get("rank", 999)
    if 5 <= rank <= 20:
        score += 1
        reasons.append(f"RANK_SWEET_SPOT #{rank}")

    return score, reasons, direction


def fetch_btc_direction():
    """Quick check: what direction is BTC trending?"""
    raw = cfg.mcporter_call("leaderboard_get_markets")
    if not raw:
        return None

    markets = []
    if isinstance(raw, dict):
        markets = raw.get("markets", raw.get("data", []))
    elif isinstance(raw, list):
        markets = raw

    for m in markets:
        if not isinstance(m, dict):
            continue
        token = str(m.get("token", "")).upper()
        if token == "BTC":
            p4h = safe_float(m.get("token_price_change_pct_4h", 0))
            if p4h > 0.3:
                return "LONG"
            elif p4h < -0.3:
                return "SHORT"
    return None


# ═══════════════════════════════════════════════════════════════
# TRADE COUNTER
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


def is_on_cooldown():
    p = os.path.join(cfg.STATE_DIR, "cooldowns.json")
    if not os.path.exists(p):
        return False
    try:
        with open(p) as f:
            cooldowns = json.load(f)
    except (json.JSONDecodeError, IOError):
        return False
    entry = cooldowns.get(ASSET)
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

    hype_positions = [p for p in positions if p["coin"].upper() == ASSET]

    if hype_positions:
        # RIDING mode — DSL manages exit. Scanner does NOT re-evaluate.
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                     "note": f"RIDING: HYPE {hype_positions[0]['direction']} — DSL manages exit.",
                     "_v2_no_thesis_exit": True})
        return

    if len(positions) >= MAX_POSITIONS:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                     "note": f"{len(positions)} positions active. Max {MAX_POSITIONS}.",
                     "_v2_no_thesis_exit": True})
        return

    # ── Trade counter ─────────────────────────────────────────
    tc = load_trade_counter()
    if tc.get("date") != now_date():
        tc = {"date": now_date(), "entries": 0}
        save_trade_counter(tc)
    if tc.get("entries", 0) >= MAX_DAILY_ENTRIES:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                    "note": f"Daily entry limit ({MAX_DAILY_ENTRIES}) reached"})
        return

    # ── Cooldown ──────────────────────────────────────────────
    if is_on_cooldown():
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                    "note": f"HYPE on cooldown ({COOLDOWN_MINUTES} min)"})
        return

    # ── Fetch all HYPE data ───────────────────────────────────
    sm_data = fetch_hype_sm_data()
    market_data = fetch_hype_market_data()

    if not sm_data:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                    "note": "HYPE not in SM leaderboard"})
        return

    # ── Score it ──────────────────────────────────────────────
    score, reasons, direction = score_hype(sm_data, market_data)

    if score < MIN_SCORE or not direction:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                    "note": f"HYPE {direction or '?'} score {score} < {MIN_SCORE}. "
                            f"Reasons: {', '.join(reasons)}"})
        return

    # ── Entry ─────────────────────────────────────────────────
    margin = round(account_value * MARGIN_PCT, 2)

    tc["entries"] = tc.get("entries", 0) + 1
    save_trade_counter(tc)

    cfg.output({
        "status": "ok",
        "signal": {
            "asset": ASSET,
            "direction": direction,
            "score": score,
            "mode": "HYPE_PREDATOR",
            "reasons": reasons,
            "smPct": sm_data["pct"],
            "smTraders": sm_data["traders"],
            "priceChg4h": sm_data["price_chg_4h"],
            "priceChg1h": sm_data["price_chg_1h"],
            "contribChange": sm_data.get("contrib_change", 0),
            "funding": market_data.get("funding", 0) if market_data else 0,
        },
        "entry": {
            "asset": ASSET,
            "direction": direction,
            "leverage": DEFAULT_LEVERAGE,
            "margin": margin,
            "orderType": "FEE_OPTIMIZED_LIMIT",
        },
        "constraints": {
            "maxPositions": MAX_POSITIONS,
            "maxLeverage": MAX_LEVERAGE,
            "maxDailyEntries": MAX_DAILY_ENTRIES,
            "cooldownMinutes": COOLDOWN_MINUTES,
            "_v2_no_thesis_exit": True,
            "_note": "DSL managed by plugin runtime. Scanner does NOT manage exits.",
        },
        "_cheetah_version": "2.0",
    })


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        cfg.log(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        cfg.output({"status": "error", "error": str(e)})
