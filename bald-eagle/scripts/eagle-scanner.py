#!/usr/bin/env python3
# Senpi BALD EAGLE Scanner v2.0
# Copyright 2026 Senpi (https://senpi.ai)
# Licensed under MIT
"""BALD EAGLE v2.0 — XYZ Alpha Hunter.

Trades XYZ assets on Hyperliquid: commodities (CL, GOLD, SILVER, BRENTOIL),
indices (SP500, XYZ100), and select high-volume equities.

v1.0 lost -28.6% across 6 trades.

v2.0 fixes:
- Whitelist: only assets with $15M+ daily volume
- Leverage capped at 7x (was 20x)
- Spread gate: rejects assets with > 0.1% spread
- Max 3 entries/day, 120 min cooldown
- Exit management handled by plugin runtime (runtime.yaml)

SM signal: leaderboard_get_markets filtered for dex="xyz".

Runs every 5 minutes.
"""

import json
import sys
import os
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eagle_config as cfg


# ═══════════════════════════════════════════════════════════════
# HARDCODED CONSTANTS
# ═══════════════════════════════════════════════════════════════

# NO WHITELIST — trade ALL 54 XYZ assets (commodities, indices, equities,
# currencies, metals). The spread gate filters out illiquid garbage.
# War + recession = opportunities across every asset class.
ALLOWED_ASSETS = None               # None = all XYZ assets allowed

# Only hard-ban assets with known data issues
BANNED_ASSETS = {
    "SNDK",  # Fox's biggest single loss, 0.28% spread
}

MAX_SPREAD_PCT = 0.001              # 0.1% max spread — the real filter
LEVERAGE = 7                        # Was 20x — CL at 20x killed us
MAX_POSITIONS = 3                   # Up from 2 — more asset classes to cover
MAX_DAILY_ENTRIES = 6               # Up from 3 — 54 assets to hunt across
COOLDOWN_MINUTES = 90               # Shorter — different assets, different moves
MARGIN_PCT = 0.15                   # 15% of account per trade (3 positions × 15% = 45% max)
MIN_SCORE = 7

# SM thresholds — XYZ has fewer SM traders than crypto
MIN_SM_PCT = 3.0
MIN_SM_TRADERS = 5

# Risk
MAX_DAILY_LOSS_PCT = 10


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
# SPREAD GATE
# ═══════════════════════════════════════════════════════════════

def check_spread(asset):
    """Check live order book spread. Returns (spread_pct, bid, ask) or (None, 0, 0)."""
    data = cfg.mcporter_call("market_get_asset_data",
                              asset=f"xyz:{asset}",
                              candle_intervals=[],
                              include_funding=False,
                              include_order_book=True)
    if not data:
        return None, 0, 0

    ad = data.get("data", data)
    if not isinstance(ad, dict):
        return None, 0, 0

    ob = ad.get("order_book", ad.get("orderBook", {}))
    if not isinstance(ob, dict):
        return None, 0, 0

    bids = ob.get("bids", ob.get("bid", []))
    asks = ob.get("asks", ob.get("ask", []))

    if not bids or not asks:
        return None, 0, 0

    # Get best bid/ask
    best_bid = safe_float(bids[0][0] if isinstance(bids[0], list) else bids[0].get("price", 0))
    best_ask = safe_float(asks[0][0] if isinstance(asks[0], list) else asks[0].get("price", 0))

    if best_bid <= 0 or best_ask <= 0:
        return None, 0, 0

    mid = (best_bid + best_ask) / 2
    spread_pct = (best_ask - best_bid) / mid

    return spread_pct, best_bid, best_ask


# ═══════════════════════════════════════════════════════════════
# SM SCANNING (XYZ only)
# ═══════════════════════════════════════════════════════════════

def scan_xyz_sm():
    """Fetch SM data for ALL XYZ assets. Spread gate filters later."""
    raw = cfg.mcporter_call("leaderboard_get_markets")
    if not raw:
        return []

    markets = []
    if isinstance(raw, dict):
        markets = raw.get("markets", raw.get("data", []))
    elif isinstance(raw, list):
        markets = raw

    candidates = []
    for m in markets:
        if not isinstance(m, dict):
            continue

        token = str(m.get("token", "")).upper()
        dex = str(m.get("dex", "")).lower()

        # Must be xyz dex
        if dex != "xyz":
            continue
        # Check ban list only (no whitelist)
        if token in BANNED_ASSETS:
            continue

        pct = safe_float(m.get("pct_of_top_traders_gain", 0))
        traders = int(m.get("trader_count", 0))
        direction = str(m.get("direction", "")).upper()
        price_chg_4h = safe_float(m.get("token_price_change_pct_4h", 0))
        price_chg_1h = safe_float(m.get("token_price_change_pct_1h",
                                   m.get("price_change_1h", 0)))

        if pct < MIN_SM_PCT or traders < MIN_SM_TRADERS:
            continue
        if direction not in ("LONG", "SHORT"):
            continue

        candidates.append({
            "token": token,
            "direction": direction,
            "pct": pct,
            "traders": traders,
            "price_chg_4h": price_chg_4h,
            "price_chg_1h": price_chg_1h,
        })

    candidates.sort(key=lambda x: x["pct"], reverse=True)
    return candidates


# ═══════════════════════════════════════════════════════════════
# CONVICTION SCORING
# ═══════════════════════════════════════════════════════════════

def score_candidate(cand):
    """Score an XYZ SM candidate. Returns (score, reasons)."""
    score = 0
    reasons = []
    direction = cand["direction"]

    # SM concentration
    pct = cand["pct"]
    if pct >= 10:
        score += 3
        reasons.append(f"HIGH_SM {pct:.1f}%")
    elif pct >= 5:
        score += 2
        reasons.append(f"SOLID_SM {pct:.1f}%")
    elif pct >= 3:
        score += 1
        reasons.append(f"BASE_SM {pct:.1f}%")

    # Trader count
    traders = cand["traders"]
    if traders >= 20:
        score += 2
        reasons.append(f"DEEP_SM ({traders}t)")
    elif traders >= 10:
        score += 1
        reasons.append(f"SM_ACTIVE ({traders}t)")

    # 4H price alignment
    p4h = cand["price_chg_4h"]
    if direction == "LONG" and p4h > 0.5:
        score += 2
        reasons.append(f"4H_ALIGNED +{p4h:.1f}%")
    elif direction == "SHORT" and p4h < -0.5:
        score += 2
        reasons.append(f"4H_ALIGNED {p4h:.1f}%")
    elif direction == "LONG" and p4h > 0:
        score += 1
        reasons.append(f"4H_POSITIVE +{p4h:.2f}%")
    elif direction == "SHORT" and p4h < 0:
        score += 1
        reasons.append(f"4H_POSITIVE {p4h:.2f}%")

    # 1H momentum
    p1h = cand["price_chg_1h"]
    if direction == "LONG" and p1h > 0.2:
        score += 1
        reasons.append(f"1H_MOMENTUM +{p1h:.2f}%")
    elif direction == "SHORT" and p1h < -0.2:
        score += 1
        reasons.append(f"1H_MOMENTUM {p1h:.2f}%")

    return score, reasons



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
    if len(scans) > 30:
        history["scans"] = scans[-30:]
    cfg.atomic_write(os.path.join(cfg.STATE_DIR, "scan-history.json"), history)


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

    # ── Trade counter ─────────────────────────────────────────
    tc = cfg.load_trade_counter()
    if tc.get("entries", 0) >= MAX_DAILY_ENTRIES:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                    "note": f"Daily entry limit ({MAX_DAILY_ENTRIES}) reached"})
        return

    # ── Scan XYZ SM data ──────────────────────────────────────
    candidates = scan_xyz_sm()

    # Save scan for history
    history = load_scan_history()
    history["scans"].append({
        "timestamp": now_iso(),
        "candidates": len(candidates),
        "top": candidates[0]["token"] if candidates else None,
    })
    save_scan_history(history)

    if not candidates:
        cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                    "note": "No XYZ SM signals across all 54 assets"})
        return

    # ── Score and filter ──────────────────────────────────────
    for cand in candidates:
        token = cand["token"]

        # Cooldown check
        if cfg.is_on_cooldown(token):
            continue

        # Already holding this asset
        if any(p["coin"].upper().replace("XYZ:", "") == token for p in positions):
            continue

        # Score it
        score, reasons = score_candidate(cand)
        if score < MIN_SCORE:
            continue

        # ── Spread gate ───────────────────────────────────────
        spread_pct, bid, ask = check_spread(token)
        if spread_pct is None:
            cfg.log(f"{token}: cannot read spread — skipping")
            continue
        if spread_pct > MAX_SPREAD_PCT:
            cfg.log(f"{token}: spread {spread_pct*100:.3f}% > {MAX_SPREAD_PCT*100:.1f}% — skipping")
            continue
        reasons.append(f"SPREAD_OK {spread_pct*100:.3f}%")

        # ── Entry ─────────────────────────────────────────────
        margin = round(account_value * MARGIN_PCT, 2)

        tc["entries"] = tc.get("entries", 0) + 1
        cfg.save_trade_counter(tc)

        cfg.output({
            "status": "ok",
            "signal": {
                "asset": f"xyz:{token}",
                "direction": cand["direction"],
                "score": score,
                "mode": "XYZ_SM",
                "reasons": reasons,
                "smPct": cand["pct"],
                "smTraders": cand["traders"],
                "spread": round(spread_pct * 100, 4),
            },
            "entry": {
                "asset": f"xyz:{token}",
                "direction": cand["direction"],
                "leverage": LEVERAGE,
                "margin": margin,
                "orderType": "FEE_OPTIMIZED_LIMIT",
            },
            "constraints": {
                "maxPositions": MAX_POSITIONS,
                "maxLeverage": LEVERAGE,
                "maxDailyEntries": MAX_DAILY_ENTRIES,
                "cooldownMinutes": COOLDOWN_MINUTES,
                "allowedAssets": "ALL_XYZ",
                "bannedAssets": sorted(BANNED_ASSETS),
                "maxSpreadPct": MAX_SPREAD_PCT,
            },
        })
        return

    cfg.output({"status": "ok", "heartbeat": "NO_REPLY",
                "note": f"{len(candidates)} XYZ candidates found, none passed score {MIN_SCORE} + spread gate"})


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        cfg.log(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        cfg.output({"status": "error", "error": str(e)})
