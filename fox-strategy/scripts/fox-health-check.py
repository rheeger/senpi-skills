#!/usr/bin/env python3
"""
FOX Job Health Check v4 — Self-healing multi-strategy meta-watchdog (FOX v0.2)
Detects AND auto-fixes per-strategy:
1. ORPHAN_DSL: active DSL but no position → auto-deactivate (skipped on fetch error)
2. NO_DSL: position exists but no DSL → auto-create from clearinghouse data
3. SCHEMA_INVALID: DSL file exists but missing v5 keys → auto-replace with correct schema
4. DIRECTION_MISMATCH: DSL/position direction differ → auto-replace DSL
5. STATE_RECONCILED: size/entry/leverage drift → auto-update DSL state
6. DSL_STALE: DSL not checked recently → alert only
7. DSL_INACTIVE: DSL exists but active=false → auto-replace with fresh DSL
8. APPROXIMATE_DSL: DSL with approximate values → reconcile from clearinghouse

Each issue includes an `action` field: auto_deactivated, auto_created,
auto_replaced, updated_state, skipped_fetch_error, or alert_only.

Outputs pre-formatted `notifications` for LLM mandate.
"""

import json, sys, os, glob
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fox_config import (load_all_strategies, dsl_state_glob, atomic_write,
                         dsl_state_path, dsl_state_template, mcporter_call_safe,
                         validate_dsl_state, heartbeat, HEARTBEAT_FILE,
                         extract_positions_from_section, get_wallet_positions)


def get_active_dsl_states(strategy_key):
    """Read all DSL state files for a specific strategy, with schema validation."""
    states = {}
    for f in sorted(glob.glob(dsl_state_glob(strategy_key))):
        try:
            with open(f) as fh:
                state = json.load(fh)
            if not isinstance(state, dict):
                continue
            asset = os.path.basename(f).replace("dsl-", "").replace(".json", "")
            schema_ok, schema_err = validate_dsl_state(state, f)
            states[asset] = {
                "active": state.get("active", False),
                "pendingClose": state.get("pendingClose", False),
                "file": f,
                "direction": state.get("direction"),
                "lastCheck": state.get("lastCheck"),
                "strategyKey": state.get("strategyKey", strategy_key),
                "size": state.get("size"),
                "entryPrice": state.get("entryPrice"),
                "leverage": state.get("leverage"),
                "highWaterPrice": state.get("highWaterPrice"),
                "_raw": state,
                "_schema_valid": schema_ok,
                "_schema_error": schema_err,
            }
        except (json.JSONDecodeError, IOError):
            continue
    return states


def _pct_diff(a, b):
    """Return absolute percentage difference between two numbers."""
    if b == 0:
        return float("inf") if a != 0 else 0
    return abs(a - b) / abs(b) * 100


def _get_strategy_tiers(cfg):
    """Extract DSL tiers from strategy config, or None for defaults."""
    dsl_cfg = cfg.get("dsl", {})
    tiers = dsl_cfg.get("tiers")
    return tiers if isinstance(tiers, list) and len(tiers) > 0 else None


def _detect_dex(coin):
    """Detect dex from coin name prefix."""
    return "xyz" if coin.startswith("xyz:") else "hl"


def check_strategy(strategy_key, cfg):
    """Run health checks for a single strategy. Auto-heals where safe."""
    issues = []
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    wallet = cfg.get("wallet", "")
    had_fetch_error = False

    if not wallet:
        issues.append({
            "level": "CRITICAL",
            "type": "NO_WALLET",
            "strategyKey": strategy_key,
            "action": "alert_only",
            "message": f"Strategy {strategy_key}: no wallet configured"
        })
        return issues, [], []

    # Single clearinghouse call returns both crypto and xyz positions
    crypto_pos, xyz_pos, fetch_err = get_wallet_positions(wallet)
    if fetch_err:
        had_fetch_error = True
        issues.append({
            "level": "WARNING",
            "type": "FETCH_ERROR",
            "strategyKey": strategy_key,
            "action": "alert_only",
            "message": f"Strategy {strategy_key}: {fetch_err}"
        })

    all_positions = dict(crypto_pos)
    for coin, pos in xyz_pos.items():
        all_positions[coin] = pos

    dsl_states = get_active_dsl_states(strategy_key)

    # --- Check: every position has an active DSL state ---
    for coin, pos in all_positions.items():
        asset_key = coin
        if asset_key not in dsl_states:
            clean_key = coin.replace("xyz:", "")
            if clean_key in dsl_states:
                asset_key = clean_key
            else:
                # --- NO_DSL: check recently-deactivated protection ---
                clean_coin_check = coin.replace("xyz:", "")
                recently_deactivated = False
                existing_path = dsl_state_path(strategy_key, clean_coin_check)
                if os.path.exists(existing_path):
                    try:
                        with open(existing_path) as _ef:
                            existing_state = json.load(_ef)
                        if not existing_state.get("active") and existing_state.get("deactivatedAt"):
                            deact_time = datetime.fromisoformat(
                                existing_state["deactivatedAt"].replace("Z", "+00:00"))
                            deact_age_min = (now - deact_time).total_seconds() / 60
                            if deact_age_min < 15:
                                recently_deactivated = True
                                issues.append({
                                    "level": "INFO",
                                    "type": "NO_DSL",
                                    "strategyKey": strategy_key,
                                    "asset": coin,
                                    "action": "skipped_recently_deactivated",
                                    "message": f"[{strategy_key}] {coin} has no active DSL but was deactivated {round(deact_age_min)}min ago — skipping auto-create"
                                })
                    except (json.JSONDecodeError, IOError, ValueError, TypeError):
                        pass

                if recently_deactivated:
                    continue

                # --- NO_DSL auto-create ---
                entry_px = pos.get("entryPx")
                size = pos.get("size")
                leverage = pos.get("leverage")
                if entry_px and size and leverage:
                    try:
                        clean_coin = coin.replace("xyz:", "")
                        new_state = dsl_state_template(
                            asset=clean_coin, direction=pos["direction"],
                            entry_price=float(entry_px), size=float(size),
                            leverage=float(leverage), strategy_key=strategy_key,
                            strategy_id=cfg.get("strategyId"),
                            wallet=wallet,
                            tiers=_get_strategy_tiers(cfg),
                            created_by="healthcheck_auto_create",
                        )
                        new_state["dex"] = _detect_dex(coin)
                        path = dsl_state_path(strategy_key, clean_coin)
                        atomic_write(path, new_state)
                        issues.append({
                            "level": "CRITICAL",
                            "type": "NO_DSL",
                            "strategyKey": strategy_key,
                            "asset": coin,
                            "action": "auto_created",
                            "message": f"[{strategy_key}] {coin} {pos['direction']} had no DSL -- auto-created at {path}"
                        })
                    except Exception as e:
                        issues.append({
                            "level": "CRITICAL",
                            "type": "NO_DSL",
                            "strategyKey": strategy_key,
                            "asset": coin,
                            "action": "alert_only",
                            "message": f"[{strategy_key}] {coin} {pos['direction']} has NO DSL state file -- auto-create failed: {e}"
                        })
                else:
                    issues.append({
                        "level": "CRITICAL",
                        "type": "NO_DSL",
                        "strategyKey": strategy_key,
                        "asset": coin,
                        "action": "alert_only",
                        "message": f"[{strategy_key}] {coin} {pos['direction']} has NO DSL state file -- incomplete data, cannot auto-create"
                    })
                continue

        dsl = dsl_states[asset_key]

        # --- SCHEMA_INVALID: DSL file has old/wrong format ---
        if not dsl["_schema_valid"]:
            entry_px = pos.get("entryPx")
            size = pos.get("size")
            leverage = pos.get("leverage")
            if entry_px and size and leverage:
                try:
                    clean_coin = coin.replace("xyz:", "")
                    new_state = dsl_state_template(
                        asset=clean_coin, direction=pos["direction"],
                        entry_price=float(entry_px), size=float(size),
                        leverage=float(leverage), strategy_key=strategy_key,
                        strategy_id=cfg.get("strategyId"),
                        wallet=wallet,
                        tiers=_get_strategy_tiers(cfg),
                        created_by="healthcheck_schema_replace",
                    )
                    new_state["dex"] = _detect_dex(coin)
                    path = dsl_state_path(strategy_key, clean_coin)
                    atomic_write(path, new_state)
                    issues.append({
                        "level": "CRITICAL",
                        "type": "SCHEMA_INVALID",
                        "strategyKey": strategy_key,
                        "asset": coin,
                        "action": "auto_replaced",
                        "message": f"[{strategy_key}] {coin} DSL had invalid schema ({dsl['_schema_error']}) -- auto-replaced with v5 format"
                    })
                except Exception as e:
                    issues.append({
                        "level": "CRITICAL",
                        "type": "SCHEMA_INVALID",
                        "strategyKey": strategy_key,
                        "asset": coin,
                        "action": "alert_only",
                        "message": f"[{strategy_key}] {coin} DSL has invalid schema ({dsl['_schema_error']}) -- auto-replace failed: {e}"
                    })
            else:
                issues.append({
                    "level": "CRITICAL",
                    "type": "SCHEMA_INVALID",
                    "strategyKey": strategy_key,
                    "asset": coin,
                    "action": "alert_only",
                    "message": f"[{strategy_key}] {coin} DSL has invalid schema ({dsl['_schema_error']}) -- incomplete position data, cannot auto-replace"
                })
            continue

        # --- DSL_INACTIVE: auto-replace with fresh DSL ---
        if not dsl["active"] and not dsl["pendingClose"]:
            entry_px = pos.get("entryPx")
            size = pos.get("size")
            leverage = pos.get("leverage", dsl.get("leverage"))
            if entry_px and size and leverage:
                try:
                    clean_coin = coin.replace("xyz:", "")
                    new_state = dsl_state_template(
                        asset=clean_coin, direction=pos["direction"],
                        entry_price=float(entry_px), size=float(size),
                        leverage=float(leverage), strategy_key=strategy_key,
                        strategy_id=cfg.get("strategyId"),
                        wallet=wallet,
                        tiers=_get_strategy_tiers(cfg),
                        created_by="healthcheck_inactive_replace",
                    )
                    new_state["dex"] = _detect_dex(coin)
                    path = dsl_state_path(strategy_key, clean_coin)
                    atomic_write(path, new_state)
                    issues.append({
                        "level": "CRITICAL",
                        "type": "DSL_INACTIVE",
                        "strategyKey": strategy_key,
                        "asset": coin,
                        "action": "auto_replaced",
                        "message": f"[{strategy_key}] {coin} DSL was inactive -- auto-replaced with fresh DSL at {path}"
                    })
                except Exception as e:
                    issues.append({
                        "level": "CRITICAL",
                        "type": "DSL_INACTIVE",
                        "strategyKey": strategy_key,
                        "asset": coin,
                        "action": "alert_only",
                        "message": f"[{strategy_key}] {coin} has DSL state file but active=false -- auto-replace failed: {e}"
                    })
            else:
                issues.append({
                    "level": "CRITICAL",
                    "type": "DSL_INACTIVE",
                    "strategyKey": strategy_key,
                    "asset": coin,
                    "action": "alert_only",
                    "message": f"[{strategy_key}] {coin} has DSL state file but active=false -- incomplete position data, cannot auto-replace"
                })
        elif dsl["direction"] != pos["direction"]:
            # --- DIRECTION_MISMATCH auto-replace ---
            try:
                entry_px = pos.get("entryPx")
                size = pos.get("size")
                leverage = pos.get("leverage", dsl.get("leverage"))
                new_state = dsl_state_template(
                    asset=asset_key, direction=pos["direction"],
                    entry_price=float(entry_px) if entry_px else float(dsl["entryPrice"]),
                    size=float(size) if size else float(dsl["size"]),
                    leverage=float(leverage) if leverage else 10,
                    strategy_key=strategy_key,
                    strategy_id=cfg.get("strategyId"),
                    wallet=wallet,
                    tiers=_get_strategy_tiers(cfg),
                    created_by="healthcheck_direction_replace",
                )
                new_state["dex"] = _detect_dex(coin)
                new_state["previousDirection"] = dsl["direction"]
                path = dsl_state_path(strategy_key, asset_key)
                atomic_write(path, new_state)
                issues.append({
                    "level": "CRITICAL",
                    "type": "DIRECTION_MISMATCH",
                    "strategyKey": strategy_key,
                    "asset": coin,
                    "action": "auto_replaced",
                    "message": f"[{strategy_key}] {coin} was {dsl['direction']} but position is {pos['direction']} -- old DSL deactivated, new DSL created"
                })
            except Exception as e:
                issues.append({
                    "level": "CRITICAL",
                    "type": "DIRECTION_MISMATCH",
                    "strategyKey": strategy_key,
                    "asset": coin,
                    "action": "alert_only",
                    "message": f"[{strategy_key}] {coin} position is {pos['direction']} but DSL is {dsl['direction']} -- auto-replace failed: {e}"
                })
        else:
            # --- Approximate DSL reconciliation ---
            if dsl["_raw"].get("approximate"):
                on_chain_entry = pos.get("entryPx")
                on_chain_size = pos.get("size")
                on_chain_leverage = pos.get("leverage")
                if on_chain_entry and float(on_chain_entry) > 0:
                    try:
                        raw = dsl["_raw"]
                        raw["entryPrice"] = float(on_chain_entry)
                        raw["size"] = float(on_chain_size) if on_chain_size else raw["size"]
                        raw["leverage"] = float(on_chain_leverage) if on_chain_leverage else raw["leverage"]
                        raw["highWaterPrice"] = float(on_chain_entry)
                        # Recalculate absoluteFloor from real entry
                        lev = raw["leverage"]
                        retrace = raw.get("phase1", {}).get("retraceThreshold", 0.02)
                        # FOX uses decimal retrace (0.02 = 2% ROE)
                        retrace_price = retrace / lev
                        if raw["direction"] == "LONG":
                            abs_floor = round(float(on_chain_entry) * (1 - retrace_price), 6)
                        else:
                            abs_floor = round(float(on_chain_entry) * (1 + retrace_price), 6)
                        raw["phase1"]["absoluteFloor"] = abs_floor
                        raw["floorPrice"] = abs_floor
                        del raw["approximate"]
                        raw["lastReconciledAt"] = now_str
                        atomic_write(dsl["file"], raw)
                        issues.append({
                            "level": "INFO",
                            "type": "APPROXIMATE_DSL_RECONCILED",
                            "strategyKey": strategy_key,
                            "asset": coin,
                            "action": "updated_state",
                            "message": f"[{strategy_key}] {coin} approximate DSL reconciled with clearinghouse data (entry={on_chain_entry})"
                        })
                    except Exception as e:
                        issues.append({
                            "level": "WARNING",
                            "type": "APPROXIMATE_DSL_RECONCILE_FAILED",
                            "strategyKey": strategy_key,
                            "asset": coin,
                            "action": "alert_only",
                            "message": f"[{strategy_key}] {coin} approximate DSL reconciliation failed: {e}"
                        })
                    continue

            # --- Size/entry/leverage reconciliation ---
            updates = {}
            on_chain_size = pos.get("size")
            on_chain_entry = pos.get("entryPx")
            on_chain_leverage = pos.get("leverage")

            if dsl["size"] and on_chain_size and _pct_diff(float(on_chain_size), float(dsl["size"])) > 1:
                updates["size"] = float(on_chain_size)
            if dsl["entryPrice"] and on_chain_entry and _pct_diff(float(on_chain_entry), float(dsl["entryPrice"])) > 0.1:
                updates["entryPrice"] = float(on_chain_entry)
            if dsl["leverage"] and on_chain_leverage and abs(float(on_chain_leverage) - float(dsl["leverage"])) > 0.5:
                updates["leverage"] = float(on_chain_leverage)

            if updates:
                try:
                    raw = dsl["_raw"]
                    raw.update(updates)
                    if "entryPrice" in updates and dsl.get("highWaterPrice"):
                        hw = float(dsl["highWaterPrice"])
                        new_entry = updates["entryPrice"]
                        if (dsl["direction"] == "LONG" and new_entry > hw) or \
                           (dsl["direction"] == "SHORT" and new_entry < hw):
                            raw["highWaterPrice"] = new_entry
                            updates["highWaterPrice"] = new_entry
                    raw["lastReconciledAt"] = now_str
                    atomic_write(dsl["file"], raw)
                    issues.append({
                        "level": "INFO",
                        "type": "STATE_RECONCILED",
                        "strategyKey": strategy_key,
                        "asset": coin,
                        "action": "updated_state",
                        "updates": updates,
                        "message": f"[{strategy_key}] {coin} DSL reconciled: {list(updates.keys())}"
                    })
                except Exception as e:
                    issues.append({
                        "level": "WARNING",
                        "type": "RECONCILE_FAILED",
                        "strategyKey": strategy_key,
                        "asset": coin,
                        "action": "alert_only",
                        "message": f"[{strategy_key}] {coin} reconciliation failed: {e}"
                    })

        # Check DSL freshness
        if dsl.get("lastCheck"):
            try:
                last = datetime.fromisoformat(dsl["lastCheck"].replace("Z", "+00:00"))
                age_min = (now - last).total_seconds() / 60
                if age_min > 10:
                    issues.append({
                        "level": "WARNING",
                        "type": "DSL_STALE",
                        "strategyKey": strategy_key,
                        "asset": coin,
                        "action": "alert_only",
                        "message": f"[{strategy_key}] {coin} DSL last checked {round(age_min)}min ago -- cron may not be firing"
                    })
            except (ValueError, TypeError):
                pass

    # --- Check: no orphan DSL states (active but no matching position) ---
    for asset, dsl in dsl_states.items():
        if dsl["active"]:
            clean_asset = asset.replace("xyz:", "")
            if clean_asset not in all_positions and asset not in all_positions:
                xyz_asset = f"xyz:{asset}"
                if xyz_asset not in all_positions:
                    # Protect approximate DSLs from orphan false positive
                    raw = dsl["_raw"]
                    if raw.get("approximate") and raw.get("createdAt"):
                        try:
                            created = datetime.fromisoformat(raw["createdAt"].replace("Z", "+00:00"))
                            age_min = (now - created).total_seconds() / 60
                            if age_min < 10:
                                issues.append({
                                    "level": "INFO",
                                    "type": "ORPHAN_DSL",
                                    "strategyKey": strategy_key,
                                    "asset": asset,
                                    "action": "skipped_approximate_recent",
                                    "message": f"[{strategy_key}] {asset} approximate DSL is {round(age_min,1)}min old, skipping orphan check (clearinghouse may be delayed)"
                                })
                                continue
                        except (ValueError, TypeError):
                            pass

                    if had_fetch_error:
                        issues.append({
                            "level": "WARNING",
                            "type": "ORPHAN_DSL",
                            "strategyKey": strategy_key,
                            "asset": asset,
                            "action": "skipped_fetch_error",
                            "message": f"[{strategy_key}] {asset} DSL appears orphaned but skipping auto-deactivate due to fetch error"
                        })
                    else:
                        try:
                            raw = dsl["_raw"]
                            raw["active"] = False
                            raw["closeReason"] = "externally_closed_detected_by_healthcheck"
                            raw["deactivatedAt"] = now_str
                            atomic_write(dsl["file"], raw)
                            issues.append({
                                "level": "WARNING",
                                "type": "ORPHAN_DSL",
                                "strategyKey": strategy_key,
                                "asset": asset,
                                "action": "auto_deactivated",
                                "message": f"[{strategy_key}] {asset} DSL was active but no position found -- auto-deactivated"
                            })
                        except Exception as e:
                            issues.append({
                                "level": "WARNING",
                                "type": "ORPHAN_DSL",
                                "strategyKey": strategy_key,
                                "asset": asset,
                                "action": "alert_only",
                                "message": f"[{strategy_key}] {asset} DSL is orphaned -- auto-deactivate failed: {e}"
                            })

    return issues, list(all_positions.keys()), [a for a, d in dsl_states.items() if d["active"]]


# ─── Cron heartbeat monitoring ───

EXPECTED_CRONS = {
    "emerging_movers": 5,
    "dsl_combined": 10,
    "sm_flip": 15,
    "watchdog": 15,
    "health_check": 20,
}


def check_cron_heartbeats():
    """Check cron heartbeat file for stale crons. Returns list of issues."""
    issues = []
    try:
        with open(HEARTBEAT_FILE) as f:
            beats = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return issues

    now = datetime.now(timezone.utc)
    for cron_name, threshold_min in EXPECTED_CRONS.items():
        last_run = beats.get(cron_name)
        if not last_run:
            issues.append({
                "level": "WARNING",
                "type": "CRON_STALE",
                "cron": cron_name,
                "action": "alert_only",
                "message": f"Cron '{cron_name}' has never recorded a heartbeat"
            })
            continue
        try:
            last_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
            age_min = (now - last_dt).total_seconds() / 60
            if age_min > threshold_min:
                issues.append({
                    "level": "WARNING",
                    "type": "CRON_STALE",
                    "cron": cron_name,
                    "action": "alert_only",
                    "ageMinutes": round(age_min, 1),
                    "thresholdMinutes": threshold_min,
                    "message": f"Cron '{cron_name}' last ran {round(age_min)}min ago (threshold: {threshold_min}min)"
                })
        except (ValueError, TypeError):
            pass
    return issues


def main():
    heartbeat("health_check")
    now = datetime.now(timezone.utc)
    strategies = load_all_strategies()

    if not strategies:
        print(json.dumps({"status": "ok", "time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "strategies": 0, "issues": [], "notifications": [],
                          "message": "No enabled strategies"}))
        sys.exit(0)

    all_issues = []
    strategy_results = {}

    for key, cfg in strategies.items():
        issues, positions, active_dsl = check_strategy(key, cfg)
        all_issues.extend(issues)
        strategy_results[key] = {
            "positions": positions,
            "active_dsl": active_dsl,
            "issues": issues,
            "issue_count": len(issues),
            "critical_count": sum(1 for i in issues if i["level"] == "CRITICAL"),
        }

    # Check cron heartbeats
    heartbeat_issues = check_cron_heartbeats()
    all_issues.extend(heartbeat_issues)

    # Build notifications for LLM mandate
    NOTIFY_ACTIONS = {"auto_created", "auto_replaced"}
    NOTIFY_TYPES = {"NO_WALLET", "DSL_INACTIVE", "SCHEMA_INVALID"}

    notifications = []
    for issue in all_issues:
        action = issue.get("action", "")
        itype = issue.get("type", "")
        if action in NOTIFY_ACTIONS:
            notifications.append(f"AUTO-FIX [{issue.get('strategyKey','')}] {issue.get('asset','')}: {issue.get('message','')}")
        elif action == "alert_only" and itype in NOTIFY_TYPES:
            notifications.append(f"CRITICAL [{issue.get('strategyKey','')}]: {issue.get('message','')}")
        elif itype == "CRON_STALE":
            notifications.append(f"CRON STALE: {issue.get('message','')}")

    result = {
        "status": "ok" if not any(i["level"] == "CRITICAL" for i in all_issues) else "critical",
        "time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "strategies": strategy_results,
        "issues": all_issues,
        "issue_count": len(all_issues),
        "critical_count": sum(1 for i in all_issues if i["level"] == "CRITICAL"),
        "cronHeartbeats": len(heartbeat_issues),
        "notifications": notifications,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
