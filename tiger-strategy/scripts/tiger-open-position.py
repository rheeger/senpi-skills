#!/usr/bin/env python3
"""
tiger-open-position.py — Atomic position open + DSL v5 state creation for TIGER.

Opens a position via create_position, fetches actual fill data from clearinghouse,
creates a DSL v5 state file atomically, and updates tiger-state.json.

Refuses to open if:
  - Strategy is halted
  - On-chain positions >= max_slots
  - Position already exists for the asset
  - Insufficient config (no wallet)

Usage:
  python3 tiger-open-position.py --asset BTC --direction LONG --leverage 5 --margin 300
  python3 tiger-open-position.py --asset ETH --direction SHORT --leverage 7 --margin 300 --pattern COMPRESSION_BREAKOUT
"""
import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

from tiger_config import (atomic_write, create_position, get_clearinghouse,
                          get_prices, load_config, load_state, log_trade,
                          now_utc, output, save_state, WORKSPACE, STATE_DIR)

DSL_TIERS_BY_PATTERN = {
    "COMPRESSION_BREAKOUT": {
        "phase1_retrace": 0.015,
        "tiers": [
            {"triggerPct": 5, "lockPct": 20, "retrace": 0.015},
            {"triggerPct": 10, "lockPct": 50, "retrace": 0.012},
            {"triggerPct": 20, "lockPct": 70, "retrace": 0.010},
            {"triggerPct": 35, "lockPct": 80, "retrace": 0.008},
        ],
    },
    "BTC_CORRELATION_LAG": {
        "phase1_retrace": 0.015,
        "tiers": [
            {"triggerPct": 5, "lockPct": 20, "retrace": 0.015},
            {"triggerPct": 10, "lockPct": 50, "retrace": 0.012},
            {"triggerPct": 20, "lockPct": 70, "retrace": 0.010},
            {"triggerPct": 35, "lockPct": 80, "retrace": 0.008},
        ],
    },
    "MOMENTUM_BREAKOUT": {
        "phase1_retrace": 0.012,
        "tiers": [
            {"triggerPct": 5, "lockPct": 20, "retrace": 0.012},
            {"triggerPct": 10, "lockPct": 50, "retrace": 0.010},
            {"triggerPct": 20, "lockPct": 70, "retrace": 0.008},
            {"triggerPct": 35, "lockPct": 80, "retrace": 0.006},
        ],
    },
    "MEAN_REVERSION": {
        "phase1_retrace": 0.015,
        "tiers": [
            {"triggerPct": 5, "lockPct": 20, "retrace": 0.015},
            {"triggerPct": 10, "lockPct": 50, "retrace": 0.012},
            {"triggerPct": 20, "lockPct": 70, "retrace": 0.010},
            {"triggerPct": 35, "lockPct": 80, "retrace": 0.008},
        ],
    },
    "FUNDING_ARB": {
        "phase1_retrace": 0.020,
        "tiers": [
            {"triggerPct": 5, "lockPct": 20, "retrace": 0.020},
            {"triggerPct": 10, "lockPct": 50, "retrace": 0.018},
            {"triggerPct": 20, "lockPct": 70, "retrace": 0.015},
            {"triggerPct": 35, "lockPct": 80, "retrace": 0.012},
        ],
    },
}

DEFAULT_TIERS = DSL_TIERS_BY_PATTERN["COMPRESSION_BREAKOUT"]


def fail(msg, **extra):
    output({"success": False, "error": msg, **extra})
    sys.exit(1)


def _unwrap_ch(ch_data):
    """Unwrap clearinghouse response — data may be nested under 'data' key."""
    if isinstance(ch_data, dict) and "data" in ch_data and isinstance(ch_data["data"], dict):
        inner = ch_data["data"]
        if "main" in inner or "xyz" in inner:
            return inner
    return ch_data


def count_on_chain_positions(ch_data):
    """Count non-zero positions from clearinghouse data."""
    data = _unwrap_ch(ch_data)
    count = 0
    coins = []
    for section_key in ("main", "xyz"):
        section = data.get(section_key, {})
        for p in section.get("assetPositions", []):
            if not isinstance(p, dict):
                continue
            pos = p.get("position", {})
            coin = pos.get("coin", "")
            szi = float(pos.get("szi", 0))
            if coin and szi != 0:
                count += 1
                coins.append(coin)
    return count, coins


def extract_position(ch_data, coin):
    """Extract a single position's fill data from clearinghouse response."""
    data = _unwrap_ch(ch_data)
    for section_key in ("main", "xyz"):
        section = data.get(section_key, {})
        for p in section.get("assetPositions", []):
            if not isinstance(p, dict):
                continue
            pos = p.get("position", {})
            if pos.get("coin") == coin and float(pos.get("szi", 0)) != 0:
                entry_px = float(pos.get("entryPx", 0))
                szi = abs(float(pos.get("szi", 0)))
                lev_val = pos.get("leverage", {})
                if isinstance(lev_val, dict):
                    lev = float(lev_val.get("value", 0))
                else:
                    lev = float(lev_val) if lev_val else 0
                return {"entryPx": entry_px, "size": szi, "leverage": lev}
    return None


def dsl_state_dir():
    """Return the DSL state directory, matching what the DSL cron expects."""
    return os.environ.get("DSL_STATE_DIR", os.path.join(WORKSPACE, "state"))


def dsl_strategy_id(config):
    """Return the DSL strategy ID from config or environment."""
    return (os.environ.get("DSL_STRATEGY_ID")
            or config.get("strategy_id")
            or config.get("strategyId")
            or "")


def dsl_state_path(strategy_id, asset):
    """Build DSL state file path: {state_dir}/{strategy_id}/{asset}.json"""
    base = dsl_state_dir()
    asset_fn = asset.replace(":", "--")
    d = os.path.join(base, strategy_id, f"{asset_fn}.json")
    return d


def dsl_state_template(asset, direction, entry_price, size, leverage,
                        strategy_id, wallet, pattern="MANUAL", tiers=None):
    """Build a DSL v5 state file from fill data."""
    pattern_cfg = DSL_TIERS_BY_PATTERN.get(pattern, DEFAULT_TIERS)
    phase1_retrace = pattern_cfg["phase1_retrace"]
    tier_list = tiers or pattern_cfg["tiers"]

    if direction == "LONG":
        absolute_floor = entry_price * (1 - 0.10 / max(leverage, 1))
    else:
        absolute_floor = entry_price * (1 + 0.10 / max(leverage, 1))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "active": True,
        "asset": asset,
        "direction": direction,
        "leverage": leverage,
        "entryPrice": entry_price,
        "size": size,
        "wallet": wallet,
        "strategyId": strategy_id,
        "phase": 1,
        "phase1": {
            "retraceThreshold": phase1_retrace,
            "consecutiveBreachesRequired": 3,
            "absoluteFloor": round(absolute_floor, 6),
        },
        "phase2TriggerTier": 0,
        "phase2": {
            "retraceThreshold": phase1_retrace,
            "consecutiveBreachesRequired": 1,
        },
        "tiers": tier_list,
        "breachDecay": "hard",
        "closeRetries": 2,
        "closeRetryDelaySec": 3,
        "maxFetchFailures": 10,
        "currentTierIndex": -1,
        "tierFloorPrice": None,
        "highWaterPrice": entry_price,
        "floorPrice": round(absolute_floor, 6),
        "currentBreachCount": 0,
        "consecutiveFetchFailures": 0,
        "pendingClose": False,
        "lastCheck": None,
        "lastPrice": None,
        "createdAt": now,
        "pattern": pattern,
    }


def main():
    parser = argparse.ArgumentParser(description="TIGER — Atomic position open + DSL v5 creation")
    parser.add_argument("--asset", required=True, help="Asset symbol (e.g. BTC, ETH, SOL)")
    parser.add_argument("--direction", required=True, choices=["LONG", "SHORT"])
    parser.add_argument("--leverage", required=True, type=int)
    parser.add_argument("--margin", required=True, type=float, help="Margin in USD")
    parser.add_argument("--pattern", default="MANUAL", help="Signal pattern (e.g. COMPRESSION_BREAKOUT)")
    parser.add_argument("--confluence-score", type=float, default=None, dest="confluence_score")
    args = parser.parse_args()

    config = load_config()
    state = load_state()

    wallet = config.get("strategy_wallet") or config.get("strategyWallet")
    if not wallet:
        fail("no_wallet_configured")

    strategy_id = dsl_strategy_id(config)
    if not strategy_id:
        fail("no_strategy_id", detail="Set DSL_STRATEGY_ID env var or strategy_id in config")

    max_slots = config.get("max_slots", 3)

    # 1. Check halted
    if state.get("halted"):
        fail("strategy_halted", reason=state.get("halt_reason", "unknown"))

    # 2. Check on-chain positions via clearinghouse (source of truth)
    ch_data = get_clearinghouse(wallet)
    if ch_data.get("error"):
        fail("clearinghouse_failed", detail=ch_data["error"])

    on_chain_count, on_chain_coins = count_on_chain_positions(ch_data)

    if on_chain_count >= max_slots:
        fail("no_slots_available",
             on_chain=on_chain_count, max_slots=max_slots,
             positions=on_chain_coins)

    # 3. Check asset not already held
    asset_upper = args.asset.upper()
    if asset_upper in [c.upper() for c in on_chain_coins]:
        fail("position_already_exists", asset=asset_upper, positions=on_chain_coins)

    # 4. Check no existing active DSL state file
    dsl_path = dsl_state_path(strategy_id, asset_upper)
    if os.path.exists(dsl_path):
        try:
            with open(dsl_path) as f:
                existing = json.load(f)
            if existing.get("active"):
                fail("dsl_already_exists", asset=asset_upper, dslFile=dsl_path)
        except (json.JSONDecodeError, IOError):
            pass

    # 5. Open position
    order = {
        "coin": args.asset,
        "direction": args.direction,
        "leverage": args.leverage,
        "marginAmount": args.margin,
        "orderType": "MARKET",
    }

    result = create_position(wallet, [order], reason=args.pattern)

    if result.get("error"):
        fail("create_position_failed", detail=result["error"])

    # 6. Fetch actual fill data from clearinghouse (retry up to 3 times)
    approximate = False
    entry_price = 0
    size = 0
    actual_leverage = args.leverage
    max_retries = 3

    for attempt in range(1, max_retries + 1):
        try:
            if attempt > 1:
                time.sleep(2)
            ch_post = get_clearinghouse(wallet)
            pos_data = extract_position(ch_post, args.asset)
            if pos_data and pos_data["entryPx"]:
                entry_price = pos_data["entryPx"]
                size = pos_data["size"]
                actual_leverage = pos_data["leverage"] or args.leverage
                break
        except Exception:
            pass

    if not entry_price:
        # Clearinghouse didn't return fill data — approximate from market price
        approximate = True
        try:
            prices = get_prices([args.asset])
            px_data = prices.get("data", prices) if isinstance(prices, dict) else {}
            if isinstance(px_data, dict) and "prices" in px_data:
                px_data = px_data["prices"]
            market_price = float(px_data.get(args.asset, 0))
        except Exception:
            market_price = 0

        if market_price > 0:
            entry_price = market_price
            size = round(args.margin * args.leverage / market_price, 6)
        else:
            fail("fill_data_unavailable",
                 detail="Position opened but cannot determine entry price. "
                        "Health check will reconcile when clearinghouse is reachable.",
                 asset=args.asset, direction=args.direction)

    # 7. Create DSL v5 state file
    dsl_state = dsl_state_template(
        asset=asset_upper,
        direction=args.direction,
        entry_price=entry_price,
        size=size,
        leverage=actual_leverage,
        strategy_id=strategy_id,
        wallet=wallet,
        pattern=args.pattern,
    )
    if approximate:
        dsl_state["approximate"] = True

    os.makedirs(os.path.dirname(dsl_path), exist_ok=True)
    atomic_write(dsl_path, dsl_state)

    # 8. Update tiger-state.json
    now = now_utc().isoformat()
    state.setdefault("active_positions", {})[asset_upper] = {
        "direction": args.direction,
        "leverage": actual_leverage,
        "margin": args.margin,
        "entry_price": entry_price,
        "size": size,
        "opened_at": now,
        "pattern": args.pattern,
    }
    if args.confluence_score is not None:
        state["active_positions"][asset_upper]["confluence_score"] = args.confluence_score
    save_state(state)

    # 9. Log trade
    log_trade({
        "action": "OPEN",
        "asset": asset_upper,
        "direction": args.direction,
        "leverage": actual_leverage,
        "margin": args.margin,
        "entry_price": entry_price,
        "size": size,
        "pattern": args.pattern,
        "confluence_score": args.confluence_score,
    })

    # 10. Output success
    result = {
        "success": True,
        "asset": asset_upper,
        "direction": args.direction,
        "entryPrice": entry_price,
        "size": size,
        "leverage": actual_leverage,
        "margin": args.margin,
        "pattern": args.pattern,
        "dslFile": dsl_path,
        "slots_used": on_chain_count + 1,
        "slots_max": max_slots,
    }
    if args.confluence_score is not None:
        result["confluenceScore"] = args.confluence_score
    if approximate:
        result["approximate"] = True
        result["warning"] = "Fill data unavailable, DSL uses approximate values. Health check will reconcile."

    notif = (f"OPENED {asset_upper} {args.direction} | "
             f"Entry: {'${:.4g}'.format(entry_price) if entry_price else 'pending'} | "
             f"Size: {size:.4g} | Lev: {actual_leverage}x | "
             f"Pattern: {args.pattern}")
    if args.confluence_score is not None:
        notif += f" | Score: {args.confluence_score}"
    result["notifications"] = [notif]

    output(result)


if __name__ == "__main__":
    main()
