#!/usr/bin/env python3
"""SCORPION Scanner — Whale Wallet Tracker.

Tracks specific whale wallets from the leaderboard, monitors their position
changes, and mirrors entries with a delay filter (only follow if whale holds
for 10+ minutes). When a tracked whale exits, SCORPION exits immediately.

Runs every 5 minutes.
"""

import sys
import os
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scorpion_config as cfg


def discover_whales(config):
    """Find top-performing whales from leaderboard."""
    entry_cfg = config.get("entry", {})
    top_n = entry_cfg.get("topNTraders", 20)
    min_win_rate = entry_cfg.get("minWhaleWinRate", 55)
    min_trades = entry_cfg.get("minWhaleTrades", 10)

    data = cfg.mcporter_call("discovery_get_top_traders", limit=top_n, window="7d")
    if not data or not data.get("success"):
        return []

    traders = data.get("data", data)
    if isinstance(traders, dict):
        traders = traders.get("traders", [])

    whales = []
    for t in traders:
        addr = t.get("address") or t.get("ethAddress", "")
        wr = float(t.get("winRate", 0))
        trades = int(t.get("totalTrades", t.get("tradeCount", 0)))
        roe = float(t.get("roe", t.get("pnlPct", 0)))
        dd = float(t.get("maxDrawdown", 0))

        if not addr or wr < min_win_rate or trades < min_trades:
            continue

        # Score whale quality
        score = 0
        if wr >= 70:
            score += 3
        elif wr >= 60:
            score += 2
        else:
            score += 1

        if abs(dd) < 10:
            score += 2
        elif abs(dd) < 20:
            score += 1

        if roe > 50:
            score += 2
        elif roe > 20:
            score += 1

        whales.append({
            "address": addr,
            "winRate": wr,
            "trades": trades,
            "roe": roe,
            "maxDrawdown": dd,
            "score": score,
        })

    whales.sort(key=lambda x: x["score"], reverse=True)
    return whales


def get_whale_positions(address):
    """Fetch current positions of a whale."""
    data = cfg.mcporter_call("leaderboard_get_trader_positions", trader_address=address)
    if not data or not data.get("success"):
        return []

    positions = data.get("data", data)
    if isinstance(positions, dict):
        positions = positions.get("positions", [])

    result = []
    for p in positions:
        coin = p.get("coin", "")
        szi = float(p.get("szi", p.get("size", 0)))
        if coin and szi != 0:
            result.append({
                "coin": coin,
                "direction": "LONG" if szi > 0 else "SHORT",
                "size": abs(szi),
                "entryPx": float(p.get("entryPx", 0)),
                "upnl": float(p.get("unrealizedPnl", 0)),
            })
    return result


def check_persistence(state, whale_addr, coin, direction, min_minutes):
    """Check if whale has held this position for min_minutes (delay filter)."""
    key = f"{whale_addr}:{coin}:{direction}"
    tracking = state.get("tracking", {})

    if key not in tracking:
        # First seen — record but don't act
        tracking[key] = {"firstSeen": cfg.now_iso(), "ts": cfg.now_ts()}
        state["tracking"] = tracking
        return False, 0

    first_seen_ts = tracking[key].get("ts", 0)
    elapsed_min = (cfg.now_ts() - first_seen_ts) / 60

    return elapsed_min >= min_minutes, elapsed_min


def check_whale_exits(state, our_positions, whales_by_addr):
    """If a whale we followed exited, we exit too."""
    exits = []
    mirrored = state.get("mirrored", {})

    for our_coin, mirror_info in list(mirrored.items()):
        whale_addr = mirror_info.get("whaleAddress", "")
        whale_dir = mirror_info.get("whaleDirection", "")

        if whale_addr not in whales_by_addr:
            continue

        whale_positions = whales_by_addr[whale_addr]
        whale_still_holds = any(
            p["coin"] == our_coin and p["direction"] == whale_dir
            for p in whale_positions
        )

        if not whale_still_holds:
            exits.append({
                "coin": our_coin,
                "reason": f"whale_exited:{whale_addr[:10]}",
                "mirror_info": mirror_info,
            })

    return exits


def run():
    config = cfg.load_config()
    wallet, _ = cfg.get_wallet_and_strategy()

    if not wallet:
        cfg.output({"success": True, "heartbeat": "HEARTBEAT_OK", "note": "no wallet"})
        return

    tc = cfg.load_trade_counter()
    if tc.get("gate") != "OPEN":
        cfg.output({"success": True, "heartbeat": "HEARTBEAT_OK", "note": f"gate={tc['gate']}"})
        return

    account_value, our_positions = cfg.get_positions(wallet)
    max_positions = config.get("maxPositions", 3)
    our_coins = {p["coin"] for p in our_positions}

    entry_cfg = config.get("entry", {})
    state = cfg.load_state("scorpion-state.json")

    # Discover whales
    whales = discover_whales(config)
    max_whales = entry_cfg.get("maxTrackedWhales", 10)
    tracked_whales = whales[:max_whales]

    # Fetch all whale positions
    whales_by_addr = {}
    all_whale_positions = []

    for whale in tracked_whales:
        positions = get_whale_positions(whale["address"])
        whales_by_addr[whale["address"]] = positions
        for p in positions:
            p["whaleAddress"] = whale["address"]
            p["whaleScore"] = whale["score"]
            all_whale_positions.append(p)

    # CHECK 1: Whale exits — if whale we followed exited, we exit
    whale_exits = check_whale_exits(state, our_positions, whales_by_addr)
    if whale_exits:
        cfg.output({
            "success": True,
            "action": "exit",
            "exits": whale_exits,
            "note": "whale exited position — scorpion sting (immediate exit)",
        })
        # Clean up mirrored state
        for ex in whale_exits:
            state.get("mirrored", {}).pop(ex["coin"], None)
        cfg.save_state(state, "scorpion-state.json")
        return

    # CHECK 2: New entry signals
    if len(our_positions) >= max_positions:
        cfg.output({"success": True, "heartbeat": "HEARTBEAT_OK",
                     "note": f"max positions, tracking {len(tracked_whales)} whales"})
        cfg.save_state(state, "scorpion-state.json")
        return

    # Find consensus positions (multiple whales holding same direction)
    position_votes = {}
    for p in all_whale_positions:
        key = f"{p['coin']}:{p['direction']}"
        if key not in position_votes:
            position_votes[key] = {"coin": p["coin"], "direction": p["direction"],
                                    "whales": [], "totalScore": 0}
        position_votes[key]["whales"].append(p["whaleAddress"])
        position_votes[key]["totalScore"] += p["whaleScore"]

    # Score signals
    min_whale_count = entry_cfg.get("minWhaleCount", 2)
    min_hold_minutes = entry_cfg.get("minHoldMinutes", 10)
    banned = entry_cfg.get("bannedPrefixes", ["xyz:"])

    signals = []
    for key, vote in position_votes.items():
        coin = vote["coin"]
        direction = vote["direction"]

        if coin in our_coins:
            continue
        if any(coin.startswith(p) for p in banned):
            continue
        if len(vote["whales"]) < min_whale_count:
            continue

        # Persistence check — whale must have held for min_hold_minutes
        persisted, elapsed = check_persistence(
            state, vote["whales"][0], coin, direction, min_hold_minutes
        )
        if not persisted:
            continue

        score = len(vote["whales"]) * 2 + vote["totalScore"]
        reasons = [
            f"{len(vote['whales'])}_whales_aligned",
            f"held_{elapsed:.0f}min",
            f"combined_score_{vote['totalScore']}",
        ]

        signals.append({
            "coin": coin,
            "direction": direction,
            "score": score,
            "reasons": reasons,
            "whaleCount": len(vote["whales"]),
            "whaleAddresses": vote["whales"],
        })

    cfg.save_state(state, "scorpion-state.json")

    if not signals:
        cfg.output({"success": True, "heartbeat": "HEARTBEAT_OK",
                     "note": f"tracking {len(tracked_whales)} whales, no consensus signals",
                     "whales_tracked": len(tracked_whales),
                     "positions_seen": len(all_whale_positions)})
        return

    signals.sort(key=lambda x: x["score"], reverse=True)
    best = signals[0]

    leverage = config.get("leverage", {}).get("default", 8)
    margin_pct = entry_cfg.get("marginPct", 0.15)
    margin = round(account_value * margin_pct, 2)

    # Record mirror info for exit tracking
    mirrored = state.get("mirrored", {})
    mirrored[best["coin"]] = {
        "whaleAddress": best["whaleAddresses"][0],
        "whaleDirection": best["direction"],
        "enteredAt": cfg.now_iso(),
        "whaleCount": best["whaleCount"],
    }
    state["mirrored"] = mirrored
    cfg.save_state(state, "scorpion-state.json")

    cfg.output({
        "success": True,
        "signal": best,
        "entry": {
            "coin": best["coin"],
            "direction": best["direction"],
            "leverage": leverage,
            "margin": margin,
            "orderType": config.get("execution", {}).get("entryOrderType", "FEE_OPTIMIZED_LIMIT"),
        },
        "whales_tracked": len(tracked_whales),
        "candidates": len(signals),
    })


if __name__ == "__main__":
    run()
