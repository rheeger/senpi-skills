#!/usr/bin/env python3
"""
fox-open-position.py — Atomic position open + DSL v5 state creation for FOX v0.2

Opens a position via mcporter, fetches actual fill data, and creates a correct
DSL v5 state file atomically. Uses FOX tiered margin, conviction-scaled Phase 1,
and re-entry support.

Usage:
  python3 fox-open-position.py --strategy fox-abc123 --asset HYPE --direction LONG
  python3 fox-open-position.py --strategy fox-abc123 --asset HYPE --signal-index 0
"""
import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fox_config import (ROTATION_COOLDOWN_MINUTES, WORKSPACE, atomic_write,
                        calculate_leverage, count_active_dsls, dsl_state_glob,
                        dsl_state_path, dsl_state_template,
                        extract_single_position, load_strategy, mcporter_call,
                        mcporter_call_safe, strategy_lock)


def fail(msg, **extra):
    """Print error JSON and exit."""
    print(json.dumps({"success": False, "error": msg, **extra}))
    sys.exit(1)


def load_max_leverage():
    """Load max-leverage.json if it exists."""
    path = os.path.join(WORKSPACE, "max-leverage.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def load_trade_counter():
    """Load fox-trade-counter.json if it exists."""
    path = os.path.join(WORKSPACE, "fox-trade-counter.json")
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def get_tiered_margin(trade_counter, budget):
    """Get margin amount from trade counter's tiered margin system.

    Args:
        trade_counter: Parsed trade counter dict.
        budget: Strategy budget.

    Returns:
        Margin amount in USD.
    """
    if not trade_counter:
        return None
    entries = trade_counter.get("entries", 0) + 1  # next entry number
    margin_tiers = trade_counter.get("marginTiers", [])
    for tier in margin_tiers:
        entry_range = tier.get("entries", [])
        if len(entry_range) >= 2 and entry_range[0] <= entries <= entry_range[1]:
            margin_pct = tier.get("marginPct", 0)
            return round(budget * margin_pct, 2)
    # Default to last tier if beyond range
    if margin_tiers:
        return round(budget * margin_tiers[-1].get("marginPct", 0.07), 2)
    return None


def increment_trade_counter():
    """Increment the trade counter entries after a successful open."""
    path = os.path.join(WORKSPACE, "fox-trade-counter.json")
    try:
        with open(path) as f:
            counter = json.load(f)
        counter["entries"] = counter.get("entries", 0) + 1
        atomic_write(path, counter)
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        pass


def has_active_dsl(strategy_key, asset):
    """Check if an active DSL already exists for this asset in this strategy."""
    path = dsl_state_path(strategy_key, asset)
    if not os.path.exists(path):
        return False
    try:
        with open(path) as f:
            state = json.load(f)
        return state.get("active", False)
    except (json.JSONDecodeError, IOError, AttributeError):
        return False


def main():
    parser = argparse.ArgumentParser(
        description="FOX v0.2 — Atomic position open + DSL v5 creation")
    parser.add_argument("--strategy", required=True,
                        help="Strategy key (e.g. fox-abc123)")
    parser.add_argument("--asset", required=True,
                        help="Asset symbol (e.g. HYPE, BTC, xyz:AAPL)")
    parser.add_argument("--direction", required=False, default=None, choices=["LONG", "SHORT"],
                        help="Trade direction")
    parser.add_argument("--leverage", required=False, type=float, default=None,
                        help="Leverage multiplier (optional — auto-calculated from tradingRisk if omitted)")
    parser.add_argument("--conviction", type=float, default=0.5,
                        help="Signal conviction 0.0-1.0 for leverage calculation (default: 0.5)")
    parser.add_argument("--margin", type=float, default=None,
                        help="Margin override (default: tiered margin from trade counter)")
    parser.add_argument("--scanner", action="store_true", default=False,
                        help="Scanner mode: use reduced retries/timeouts for faster execution")
    parser.add_argument("--close-asset", default=None, dest="close_asset",
                        help="Asset to close before opening (rotation). Handled atomically under lock.")
    parser.add_argument("--signal-index", type=int, default=None, dest="signal_index",
                        help="Read direction/conviction/score/isReentry from Nth alert in scanner output.")
    args = parser.parse_args()

    strategy_key = args.strategy
    asset = args.asset
    leverage = args.leverage
    margin_override = args.margin

    # Resolve direction/conviction/score from scanner output if --signal-index provided
    score = None
    is_reentry = False
    reentry_of = None
    if args.signal_index is not None:
        emerging_history = os.environ.get("EMERGING_HISTORY", "")
        if emerging_history:
            scanner_output_file = os.path.join(os.path.dirname(emerging_history), "fox-emerging-movers-output.json")
        else:
            scanner_output_file = os.path.join(WORKSPACE, "fox-emerging-movers-output.json")
        try:
            with open(scanner_output_file) as f:
                scanner_output = json.load(f)
            # Look in topPicks first, then alerts
            picks = scanner_output.get("topPicks", scanner_output.get("alerts", []))
            signal = None
            for pick in picks:
                if pick.get("signalIndex") == args.signal_index:
                    signal = pick
                    break
            if signal is None and args.signal_index < len(scanner_output.get("alerts", [])):
                signal = scanner_output["alerts"][args.signal_index]
            if signal is None:
                fail("signal_index_not_found", signalIndex=args.signal_index)
            direction = signal["direction"].upper()
            conviction = signal.get("conviction", 0.5)
            score = signal.get("score")
            is_reentry = signal.get("isReentry", False)
            reentry_of = signal.get("reentryOf")
        except (FileNotFoundError, json.JSONDecodeError, IndexError, KeyError) as e:
            fail("signal_index_failed", detail=str(e), signalIndex=args.signal_index)
    else:
        if not args.direction:
            fail("missing_direction", detail="--direction is required when --signal-index is not used")
        direction = args.direction.upper()
        conviction = args.conviction

    # 1. Load strategy config
    try:
        cfg = load_strategy(strategy_key)
    except SystemExit:
        sys.exit(1)

    wallet = cfg.get("wallet", "")
    if not wallet:
        fail("no_wallet_configured", strategyKey=strategy_key)

    # 2. Determine margin — tiered margin system
    if margin_override:
        margin = margin_override
    else:
        trade_counter = load_trade_counter()
        budget = cfg.get("budget", 0)
        tiered_margin = get_tiered_margin(trade_counter, budget)
        if tiered_margin and tiered_margin > 0:
            # Re-entry uses 75% of normal margin
            if is_reentry:
                margin = round(tiered_margin * 0.75, 2)
            else:
                margin = tiered_margin
        else:
            margin = cfg.get("marginPerSlot", 0)

    if margin <= 0:
        fail("invalid_margin", margin=margin, strategyKey=strategy_key)

    # 3. Resolve leverage
    max_lev_data = load_max_leverage()
    clean_asset = asset.replace("xyz:", "")
    lookup_key = asset if asset in max_lev_data else clean_asset
    max_lev = max_lev_data.get(lookup_key)
    leverage_capped = False
    leverage_auto = False

    if leverage is None:
        trading_risk = cfg.get("tradingRisk", "moderate")
        if max_lev is not None:
            leverage = calculate_leverage(max_lev, trading_risk, conviction)
            leverage_auto = True
        else:
            leverage = cfg.get("defaultLeverage", 10)
    else:
        if max_lev is not None and leverage > max_lev:
            original_leverage = leverage
            leverage = max_lev
            leverage_capped = True

    # Scanner mode: 2 retries x 15s for faster execution within cron timeout
    api_retries = 2 if args.scanner else 3
    api_timeout = 15 if args.scanner else 30

    # Acquire strategy lock to serialize slot check + position open + DSL write
    try:
        lock_ctx = strategy_lock(strategy_key, timeout=120)
        lock_ctx.__enter__()
    except RuntimeError as e:
        fail("lock_timeout", detail=str(e), strategyKey=strategy_key)

    try:
        # 4. Handle rotation close (--close-asset) inside the lock
        just_closed_coin = None
        rotation_notif = None
        if args.close_asset:
            close_clean = args.close_asset.replace("xyz:", "")

            # Enforce rotation cooldown
            close_dsl_path = dsl_state_path(strategy_key, close_clean)
            if os.path.exists(close_dsl_path):
                try:
                    with open(close_dsl_path) as f:
                        close_state = json.load(f)
                    if close_state.get("createdAt"):
                        created = datetime.fromisoformat(close_state["createdAt"].replace("Z", "+00:00"))
                        age_min = (datetime.now(timezone.utc) - created).total_seconds() / 60
                        if age_min < ROTATION_COOLDOWN_MINUTES:
                            fail("rotation_cooldown",
                                 detail=f"{close_clean} is {round(age_min, 1)}min old, cooldown is {ROTATION_COOLDOWN_MINUTES}min",
                                 closeAsset=close_clean, strategyKey=strategy_key)
                except (json.JSONDecodeError, IOError, ValueError, TypeError):
                    pass

            # Determine on-chain coin name for close
            close_is_xyz = args.close_asset.startswith("xyz:") or cfg.get("dex") == "xyz"
            if not close_is_xyz:
                xyz_key = f"xyz:{args.close_asset}"
                if xyz_key in max_lev_data and args.close_asset not in max_lev_data:
                    close_is_xyz = True
            close_coin = (args.close_asset if args.close_asset.startswith("xyz:")
                          else (f"xyz:{args.close_asset}" if close_is_xyz
                                else args.close_asset))

            try:
                mcporter_call("close_position",
                              retries=api_retries, timeout=api_timeout,
                              strategyWalletAddress=wallet,
                              coin=close_coin, reason="rotation_for_stronger_signal")
            except RuntimeError as e:
                fail("rotation_close_failed", detail=str(e),
                     closeAsset=close_clean, strategyKey=strategy_key)

            close_dsl_path = dsl_state_path(strategy_key, close_clean)
            if os.path.exists(close_dsl_path):
                try:
                    with open(close_dsl_path) as f:
                        close_state = json.load(f)
                    close_state["active"] = False
                    close_state["closeReason"] = "rotation_for_stronger_signal"
                    close_state["closedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    atomic_write(close_dsl_path, close_state)
                except (json.JSONDecodeError, IOError):
                    pass

            just_closed_coin = close_coin
            rotation_notif = f"ROTATION [{strategy_key}]: Closing {close_clean} for {clean_asset}"

        # 5. Check slot availability (cross-check DSL files with on-chain positions)
        max_slots = cfg.get("slots", cfg.get("maxEntries", 2))
        dsl_count = count_active_dsls(dsl_state_glob(strategy_key))
        on_chain_count = 0
        ch_data = None
        if wallet:
            ch_data = mcporter_call_safe("strategy_get_clearinghouse_state",
                                          strategy_wallet=wallet)
            if ch_data:
                for section_key in ("main", "xyz"):
                    section = ch_data.get(section_key, {})
                    for p in section.get("assetPositions", []):
                        if not isinstance(p, dict):
                            continue
                        pos = p.get("position", {})
                        szi = float(pos.get("szi", 0))
                        if szi != 0:
                            on_chain_count += 1

        # Adjust on_chain_count for position we just closed
        if just_closed_coin and on_chain_count > 0 and ch_data:
            for section_key in ("main", "xyz"):
                section = ch_data.get(section_key, {})
                for p in section.get("assetPositions", []):
                    if not isinstance(p, dict):
                        continue
                    pos = p.get("position", {})
                    if pos.get("coin") == just_closed_coin and float(pos.get("szi", 0)) != 0:
                        on_chain_count -= 1
                        break

        active_count = max(dsl_count, on_chain_count)
        if active_count >= max_slots:
            fail("no_slots_available", used=active_count, max=max_slots,
                 dslCount=dsl_count, onChainCount=on_chain_count,
                 strategyKey=strategy_key)

        # 6. Check no existing active DSL for this asset
        if has_active_dsl(strategy_key, clean_asset):
            fail("position_already_exists", asset=clean_asset,
                 strategyKey=strategy_key)

        # 7. Detect dex
        is_xyz = asset.startswith("xyz:") or cfg.get("dex") == "xyz"
        if not is_xyz and not asset.startswith("xyz:"):
            xyz_key = f"xyz:{asset}"
            if xyz_key in max_lev_data and asset not in max_lev_data:
                is_xyz = True
        dex = "xyz" if is_xyz else "hl"
        coin = asset if asset.startswith("xyz:") else (f"xyz:{asset}" if is_xyz else asset)

        # 8. Open position via mcporter
        order = {
            "coin": coin,
            "direction": direction,
            "leverage": int(leverage),
            "marginAmount": margin,
            "orderType": "MARKET",
        }
        if is_xyz:
            order["leverageType"] = "ISOLATED"

        try:
            open_result = mcporter_call(
                "create_position",
                retries=api_retries, timeout=api_timeout,
                strategyWalletAddress=wallet,
                orders=[order],
            )
        except RuntimeError as e:
            fail("position_open_failed", detail=str(e), strategyKey=strategy_key)

        # 9. Fetch actual fill data from clearinghouse
        approximate = False
        try:
            ch_data = mcporter_call("strategy_get_clearinghouse_state",
                                    retries=api_retries, timeout=api_timeout,
                                    strategy_wallet=wallet)
            pos_data = extract_single_position(ch_data, coin, dex=("xyz" if is_xyz else None))
            if pos_data:
                entry_price = pos_data["entryPx"]
                size = pos_data["size"]
                actual_leverage = pos_data["leverage"] or leverage
                if not entry_price:
                    approximate = True
            else:
                approximate = True
                entry_price = 0
                size = round(margin * leverage, 6)
                actual_leverage = leverage
        except RuntimeError:
            approximate = True
            entry_price = 0
            size = round(margin * leverage, 6)
            actual_leverage = leverage

        # 10. Create DSL v5 state
        tiers = None
        dsl_cfg = cfg.get("dsl", {})
        if isinstance(dsl_cfg.get("tiers"), list) and len(dsl_cfg["tiers"]) > 0:
            tiers = dsl_cfg["tiers"]

        dsl_asset = coin if is_xyz else clean_asset
        dsl_state = dsl_state_template(
            asset=dsl_asset,
            direction=direction,
            entry_price=entry_price,
            size=size,
            leverage=actual_leverage,
            strategy_key=strategy_key,
            strategy_id=cfg.get("strategyId"),
            wallet=wallet,
            tiers=tiers,
            created_by="open_position_script",
            score=score,
            is_reentry=is_reentry,
            reentry_of=reentry_of,
        )
        dsl_state["dex"] = dex
        if approximate:
            dsl_state["approximate"] = True

        # 11. Write DSL state atomically
        dsl_path = dsl_state_path(strategy_key, dsl_asset)
        atomic_write(dsl_path, dsl_state)
    finally:
        lock_ctx.__exit__(None, None, None)

    # 12. Increment trade counter
    increment_trade_counter()

    # 13. Output result
    result = {
        "success": True,
        "asset": clean_asset,
        "direction": direction,
        "entryPrice": entry_price,
        "size": size,
        "leverage": actual_leverage,
        "dslFile": dsl_path,
        "strategyKey": strategy_key,
    }
    if score is not None:
        result["score"] = score
    if is_reentry:
        result["isReentry"] = True
        result["reentryOf"] = reentry_of
    if approximate:
        result["approximate"] = True
        result["warning"] = "Fill data unavailable, DSL uses approximate values. Health check will reconcile."
    if leverage_capped:
        result["leverageCapped"] = True
        result["requestedLeverage"] = original_leverage
        result["maxLeverage"] = max_lev
    if leverage_auto:
        result["leverageAutoCalculated"] = True
        result["tradingRisk"] = cfg.get("tradingRisk", "moderate")
        result["conviction"] = conviction
        if max_lev is not None:
            result["maxLeverage"] = max_lev

    # Build pre-formatted notification messages
    notif_parts = [f"OPENED {clean_asset} {direction} [{strategy_key}]"]
    notif_parts.append(f"Entry: ${entry_price:.4g}" if entry_price else "Entry: pending fill")
    notif_parts.append(f"Size: {size:.4g}")
    notif_parts.append(f"Leverage: {actual_leverage}x")
    if score is not None:
        notif_parts.append(f"Score: {score}")
    if is_reentry:
        notif_parts.append("RE-ENTRY")
    if leverage_auto:
        notif_parts.append(f"(auto: {cfg.get('tradingRisk', 'moderate')} risk, {conviction} conviction)")
    if leverage_capped:
        notif_parts.append(f"(capped from {original_leverage}x, max {max_lev}x)")
    result["notifications"] = [" | ".join(notif_parts)]
    if rotation_notif:
        result["notifications"].insert(0, rotation_notif)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
