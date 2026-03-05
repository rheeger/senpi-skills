#!/usr/bin/env python3
"""
fox-dsl-wrapper.py — DSL v5 runner + Phase 1 timing enforcement for FOX v0.2

Moves Phase 1 timing enforcement from the cron mandate into a script.
1. Runs external dsl-v5.py via subprocess, captures ndjson output.
2. Parses DSL output into notifications + action_required.
3. Applies Phase 1 timing enforcement (dead weight, weak peak, hard timeout, green-in-10).
4. Outputs JSON: {"notifications": [...], "action_required": [...]}

Usage:
  python3 fox-dsl-wrapper.py
  python3 fox-dsl-wrapper.py --strategy fox-abc123
  python3 fox-dsl-wrapper.py --help
"""
import json, sys, os, subprocess, glob, argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fox_config import (load_strategy, load_all_strategies, atomic_write,
                         mcporter_call_safe, heartbeat, dsl_state_path,
                         dsl_state_glob, WORKSPACE, CONVICTION_TIERS,
                         _get_conviction_tier, extract_positions_from_section)

DSL_V5_SCRIPT = os.path.join(WORKSPACE, "skills", "dsl-dynamic-stop-loss", "scripts", "dsl-v5.py")


def run_dsl_v5(strategy_id):
    """Run the external dsl-v5.py script and capture its ndjson output.

    Args:
        strategy_id: Strategy UUID for DSL_STRATEGY_ID env var.

    Returns:
        List of parsed JSON dicts (one per line of ndjson output).
    """
    env = os.environ.copy()
    env["DSL_STATE_DIR"] = os.path.join(WORKSPACE, "dsl")
    env["DSL_STRATEGY_ID"] = strategy_id
    env["PYTHONUNBUFFERED"] = "1"

    try:
        result = subprocess.run(
            ["python3", DSL_V5_SCRIPT],
            env=env, capture_output=True, text=True, timeout=120,
        )
        lines = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                lines.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return lines
    except (subprocess.TimeoutExpired, OSError) as e:
        return [{"status": "error", "error": f"dsl-v5.py execution failed: {e}"}]


def get_strategy_positions_roe(wallet):
    """Get current ROE for all positions from clearinghouse.

    Returns dict of coin → ROE percentage.
    """
    roe_map = {}
    data = mcporter_call_safe("strategy_get_clearinghouse_state", strategy_wallet=wallet)
    if not data:
        return roe_map
    for section_key in ("main", "xyz"):
        section = data.get(section_key, {})
        if not isinstance(section, dict):
            continue
        for p in section.get("assetPositions", []):
            if not isinstance(p, dict):
                continue
            pos = p.get("position", {})
            coin = pos.get("coin", "")
            szi = float(pos.get("szi", 0))
            if coin and szi != 0:
                roe = float(pos.get("returnOnEquity", 0)) * 100
                roe_map[coin] = roe
                # Also store without xyz: prefix
                if coin.startswith("xyz:"):
                    roe_map[coin.replace("xyz:", "")] = roe
    return roe_map


def enforce_phase1_timing(strategy_key, cfg, notifications, action_required):
    """Check Phase 1 timing rules for all active Phase 1 positions.

    Dead weight, weak peak, hard timeout, green-in-10.
    """
    wallet = cfg.get("wallet", "")
    if not wallet:
        return

    now = datetime.now(timezone.utc)

    # Get current ROE from clearinghouse
    roe_map = get_strategy_positions_roe(wallet)

    # Scan all active DSL state files for Phase 1 positions
    for sf in glob.glob(dsl_state_glob(strategy_key)):
        try:
            with open(sf) as f:
                state = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        if not state.get("active"):
            continue
        if state.get("phase", 0) != 1:
            continue

        asset = state.get("asset", "")
        direction = state.get("direction", "")
        created_at = state.get("createdAt")
        if not created_at:
            continue

        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_min = (now - created).total_seconds() / 60
        except (ValueError, TypeError):
            continue

        # Get conviction-scaled timing from state (set at entry) or derive from score
        phase1 = state.get("phase1", {})
        score = state.get("score")
        conviction = _get_conviction_tier(score)

        hard_timeout = phase1.get("hardTimeoutMin", conviction["hardTimeoutMin"])
        weak_peak = phase1.get("weakPeakCutMin", conviction["weakPeakCutMin"])
        dead_weight = phase1.get("deadWeightCutMin", conviction["deadWeightCutMin"])

        # Get current ROE
        current_roe = roe_map.get(asset, roe_map.get(f"xyz:{asset}"))
        if current_roe is None:
            continue

        # Track peak ROE (use highWaterPrice as proxy if available)
        # Note: We're using current ROE for timing checks. Peak ROE tracking
        # is approximate — the DSL state's highWaterPrice tracks price, not ROE.

        # 1. DEAD WEIGHT: age > deadWeightCutMin AND ROE <= 0%
        if age_min > dead_weight and current_roe <= 0:
            action_required.append({
                "action": "close_position",
                "coin": asset,
                "strategyKey": strategy_key,
                "wallet": wallet,
                "direction": direction,
                "reason": f"Dead weight: {round(age_min, 1)}min old, ROE {round(current_roe, 1)}% (never positive after {dead_weight}min)"
            })
            notifications.append(
                f"PHASE1 CUT [{strategy_key}]: {asset} {direction} — dead weight "
                f"({round(age_min, 1)}min, ROE {round(current_roe, 1)}%)"
            )
            continue

        # 2. WEAK PEAK: age > weakPeakCutMin AND peak ROE < 3% AND declining
        if age_min > weak_peak and current_roe < 3 and current_roe > 0:
            # Check if declining by comparing to highWaterPrice
            hw = state.get("highWaterPrice", state.get("entryPrice", 0))
            entry = state.get("entryPrice", 0)
            if hw and entry and hw > 0:
                if direction == "LONG":
                    hw_roe = (hw - entry) / entry * state.get("leverage", 10) * 100
                else:
                    hw_roe = (entry - hw) / entry * state.get("leverage", 10) * 100
                if hw_roe >= current_roe + 0.5:  # declining from peak
                    action_required.append({
                        "action": "close_position",
                        "coin": asset,
                        "strategyKey": strategy_key,
                        "wallet": wallet,
                        "direction": direction,
                        "reason": f"Weak peak: {round(age_min, 1)}min old, peak ROE ~{round(hw_roe, 1)}% < 3%, declining to {round(current_roe, 1)}%"
                    })
                    notifications.append(
                        f"PHASE1 CUT [{strategy_key}]: {asset} {direction} — weak peak "
                        f"({round(age_min, 1)}min, ROE {round(current_roe, 1)}%)"
                    )
                    continue

        # 3. HARD TIMEOUT: age > hardTimeoutMin AND still Phase 1
        if age_min > hard_timeout:
            action_required.append({
                "action": "close_position",
                "coin": asset,
                "strategyKey": strategy_key,
                "wallet": wallet,
                "direction": direction,
                "reason": f"Hard timeout: {round(age_min, 1)}min in Phase 1 (limit: {hard_timeout}min), ROE {round(current_roe, 1)}%"
            })
            notifications.append(
                f"PHASE1 CUT [{strategy_key}]: {asset} {direction} — hard timeout "
                f"({round(age_min, 1)}min, ROE {round(current_roe, 1)}%)"
            )
            continue

        # 4. GREEN-IN-10: age > 10min AND greenIn10 == false AND ROE was never positive
        if age_min > 10 and not state.get("greenIn10", False) and current_roe <= 0:
            # Tighten floor to 50% of original distance
            abs_floor = phase1.get("absoluteFloor")
            entry_price = state.get("entryPrice")
            if abs_floor and entry_price:
                original_distance = abs(entry_price - abs_floor)
                new_distance = original_distance * 0.5
                if direction == "LONG":
                    new_floor = round(entry_price - new_distance, 6)
                else:
                    new_floor = round(entry_price + new_distance, 6)

                # Update state file (tighten, don't close)
                state["phase1"]["absoluteFloor"] = new_floor
                state["floorPrice"] = new_floor
                state["greenIn10"] = False  # Keep tracking
                state["greenIn10Tightened"] = True
                state["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                atomic_write(sf, state)

                notifications.append(
                    f"GREEN-IN-10 [{strategy_key}]: {asset} {direction} — floor tightened "
                    f"to {new_floor:.6g} (50% of original distance, ROE {round(current_roe, 1)}%)"
                )

        # Track if position goes green (update greenIn10)
        if current_roe > 0 and not state.get("greenIn10", False):
            state["greenIn10"] = True
            state["updatedAt"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            atomic_write(sf, state)


def main():
    parser = argparse.ArgumentParser(
        description="FOX v0.2 — DSL v5 wrapper + Phase 1 timing enforcement")
    parser.add_argument("--strategy", default=None,
                        help="Strategy key (optional — runs all if omitted)")
    args = parser.parse_args()

    heartbeat("dsl_combined")

    notifications = []
    action_required = []

    if args.strategy:
        strategies = {args.strategy: load_strategy(args.strategy)}
    else:
        strategies = load_all_strategies()

    for strategy_key, cfg in strategies.items():
        strategy_id = cfg.get("strategyId", "")
        if not strategy_id:
            continue

        # 1. Run external DSL v5
        dsl_results = run_dsl_v5(strategy_id)

        # 2. Parse DSL output
        for entry in dsl_results:
            asset = entry.get("asset", "")
            status = entry.get("status", "")

            if entry.get("closed"):
                direction = entry.get("direction", "")
                close_reason = entry.get("close_reason", "")
                upnl = entry.get("upnl", 0)
                notifications.append(
                    f"DSL CLOSED [{strategy_key}]: {asset} {direction} — "
                    f"{close_reason}, PnL: ${upnl:.2f}" if isinstance(upnl, (int, float)) else
                    f"DSL CLOSED [{strategy_key}]: {asset} {direction} — {close_reason}"
                )

            if entry.get("pending_close"):
                notifications.append(
                    f"DSL RETRY [{strategy_key}]: {asset} — close pending, will retry"
                )

            if entry.get("tier_changed"):
                new_tier = entry.get("new_tier", "")
                notifications.append(
                    f"DSL TIER [{strategy_key}]: {asset} — tier changed to {new_tier}"
                )

            if status == "error":
                failures = entry.get("consecutive_failures", 0)
                if failures >= 3:
                    notifications.append(
                        f"DSL ERROR [{strategy_key}]: {asset} — "
                        f"{failures} consecutive failures: {entry.get('error', 'unknown')}"
                    )

            if status == "strategy_inactive":
                notifications.append(
                    f"DSL INACTIVE [{strategy_key}]: strategy inactive — remove cron"
                )

        # 3. Phase 1 timing enforcement
        enforce_phase1_timing(strategy_key, cfg, notifications, action_required)

    # 4. Output
    output = {
        "notifications": notifications,
        "action_required": action_required,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
