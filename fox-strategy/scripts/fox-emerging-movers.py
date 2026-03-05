#!/usr/bin/env python3
"""Emerging Movers Detector v5 — FOX v0.2 production-ready
Tracks SM market concentration rank changes over time.
Flags assets accelerating up the ranks EARLY — catch at #50→#20, not #5.

v5 changes (FOX v0.2):
- ALL entry logic moved to script: scoring, re-entry detection, market regime gate.
- Outputs topPicks with pre-built entryCommands for the LLM mandate.
- Heartbeat, max-leverage, on-chain slot cross-check, rotation eligibility.
- Saves output to file (prevent signal loss on re-run).
- signalIndex on each alert for fox-open-position.py --signal-index.
- Removed time-of-day scoring.

Uses: leaderboard_get_markets (single API call)
"""
import json, sys, os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fox_config import (atomic_write, mcporter_call, mcporter_call_safe,
                         load_all_strategies, dsl_state_glob,
                         heartbeat, SIGNAL_CONVICTION, WORKSPACE,
                         ROTATION_COOLDOWN_MINUTES, count_active_dsls)

heartbeat("emerging_movers")

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.environ.get("EMERGING_HISTORY",
    os.path.join(WORKSPACE, "fox-emerging-movers-history.json"))
MAX_LEV_FILE = os.path.join(WORKSPACE, "max-leverage.json")

# Load max-leverage data (file-based, no API call — speed critical for 3min scanner)
try:
    with open(MAX_LEV_FILE) as f:
        MAX_LEV_DATA = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    MAX_LEV_DATA = {}

# Load market regime for score threshold
REGIME_FILE = os.path.join(WORKSPACE, "market-regime-last.json")
try:
    with open(REGIME_FILE) as f:
        REGIME_DATA = json.load(f)
    MARKET_REGIME = REGIME_DATA.get("market_regime", "BULLISH")
except (FileNotFoundError, json.JSONDecodeError):
    MARKET_REGIME = "BULLISH"

MAX_HISTORY = 60
TOP_N = 50
RANK_CLIMB_THRESHOLD = 3
CONTRIBUTION_ACCEL_THRESHOLD = 0.003
MIN_SCANS_FOR_TREND = 2
MIN_VELOCITY_FOR_DEEP_CLIMBER = 0.0003  # 0.03% — only applies to DEEP_CLIMBER
ERRATIC_REVERSAL_THRESHOLD = 5

# FOX scoring thresholds
SCORE_THRESHOLD = 6
SCORE_THRESHOLD_NEUTRAL = 8
MIN_RANK_JUMP = 15
MIN_VELOCITY_OVERRIDE = 15
MIN_MAX_LEVERAGE = 7
REENTRY_SCORE_THRESHOLD = 5
REENTRY_WINDOW_MINUTES = 120
REENTRY_MAX_LOSS_ROE = 15
REENTRY_MIN_VELOCITY = 5

# ─── Load history ───
try:
    with open(HISTORY_FILE) as f:
        history = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    history = {"scans": []}

# ─── Fetch current market concentration ───
try:
    data = mcporter_call("leaderboard_get_markets", limit=100)
    raw_markets = data["markets"]["markets"]
except Exception as e:
    print(json.dumps({"status": "error", "error": str(e)}))
    sys.exit(1)

# ─── Parse current scan ───
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
current_scan = {
    "time": now,
    "markets": []
}

for i, m in enumerate(raw_markets[:TOP_N]):
    current_scan["markets"].append({
        "token": m["token"],
        "dex": m.get("dex", ""),
        "rank": i + 1,
        "direction": m["direction"],
        "contribution": round(m["pct_of_top_traders_gain"], 6),
        "traders": m["trader_count"],
        "price_chg_4h": round(m.get("token_price_change_pct_4h") or 0, 4)
    })

# ─── Helper: previous scan token set ───
prev_scans = history["scans"]
prev_top50_tokens = set()
if prev_scans:
    for m in prev_scans[-1]["markets"]:
        prev_top50_tokens.add((m["token"], m.get("dex", "")))

def get_market_in_scan(scan, token, dex=""):
    for m in scan["markets"]:
        if m["token"] == token and m.get("dex", "") == dex:
            return m
    return None

# ─── Analyze trends ───
alerts = []

if len(prev_scans) >= MIN_SCANS_FOR_TREND:
    latest_prev = prev_scans[-1]
    oldest_available = prev_scans[-min(len(prev_scans), 5)]

    for market in current_scan["markets"]:
        token = market["token"]
        dex = market.get("dex", "")
        current_rank = market["rank"]
        current_contrib = market["contribution"]

        prev_market = get_market_in_scan(latest_prev, token, dex)
        old_market = get_market_in_scan(oldest_available, token, dex)

        alert_reasons = []
        is_deep_climber = False
        is_immediate = False
        is_first_jump = False
        is_contrib_explosion = False
        rank_jump_this_scan = 0

        # 1. Fresh entry — wasn't in top 50 last scan
        if prev_market is None:
            if current_rank <= 20:
                alert_reasons.append(f"NEW_ENTRY_DEEP at rank #{current_rank}")
                is_deep_climber = True
                is_immediate = True
            elif current_rank <= 35:
                alert_reasons.append(f"NEW_ENTRY at rank #{current_rank}")

        # 2. Rank climbing (single scan) — IMMEDIATE_MOVER / FIRST_JUMP detection
        if prev_market:
            rank_change_1 = prev_market["rank"] - current_rank
            rank_jump_this_scan = rank_change_1
            if rank_change_1 >= 2:
                alert_reasons.append(f"RANK_UP +{rank_change_1} (#{prev_market['rank']}→#{current_rank})")
            if rank_change_1 >= 10 and prev_market["rank"] >= 25:
                is_deep_climber = True
                is_immediate = True
                alert_reasons.append(f"IMMEDIATE_MOVER +{rank_change_1} from #{prev_market['rank']} in ONE scan")
                was_in_prev = (token, dex) in prev_top50_tokens
                if not was_in_prev or prev_market["rank"] >= 30:
                    is_first_jump = True
                    alert_reasons.append(f"FIRST_JUMP from #{prev_market['rank']}→#{current_rank} — highest priority")
            elif rank_change_1 >= 5 and prev_market["rank"] >= 25:
                is_deep_climber = True
                alert_reasons.append(f"DEEP_CLIMBER +{rank_change_1} from #{prev_market['rank']}")

        # 3. Contribution explosion — 3x+ increase in one scan
        if prev_market and prev_market["contribution"] > 0:
            contrib_ratio = current_contrib / prev_market["contribution"]
            if contrib_ratio >= 3.0:
                alert_reasons.append(f"CONTRIB_EXPLOSION {contrib_ratio:.1f}x in one scan ({prev_market['contribution']*100:.2f}→{current_contrib*100:.2f})")
                is_contrib_explosion = True
                if prev_market["rank"] >= 20:
                    is_immediate = True
                    is_deep_climber = True

        # 4. Multi-scan climb
        if old_market:
            rank_change_total = old_market["rank"] - current_rank
            if rank_change_total >= RANK_CLIMB_THRESHOLD:
                alert_reasons.append(f"CLIMBING +{rank_change_total} over {min(len(prev_scans), 5)} scans")
            if rank_change_total >= 10 and old_market["rank"] >= 30:
                is_deep_climber = True
                if not any("DEEP_CLIMBER" in r for r in alert_reasons) and not any("IMMEDIATE" in r for r in alert_reasons):
                    alert_reasons.append(f"DEEP_CLIMBER +{rank_change_total} from #{old_market['rank']} over {min(len(prev_scans), 5)} scans")

        # 5. Contribution acceleration
        if prev_market:
            contrib_delta = current_contrib - prev_market["contribution"]
            if contrib_delta >= CONTRIBUTION_ACCEL_THRESHOLD:
                alert_reasons.append(f"ACCEL +{contrib_delta:.3f} contribution")

        # 6. Consistent climb streak
        if len(prev_scans) >= 3:
            ranks = []
            for scan in prev_scans[-3:]:
                m = get_market_in_scan(scan, token, dex)
                if m:
                    ranks.append(m["rank"])
                else:
                    ranks.append(TOP_N + 1)
            ranks.append(current_rank)

            if all(ranks[i] >= ranks[i+1] for i in range(len(ranks)-1)) and ranks[0] > ranks[-1]:
                streak = ranks[0] - ranks[-1]
                if streak >= 2:
                    alert_reasons.append(f"STREAK climbing {streak} ranks over 4 checks")

        # Calculate contribution velocity
        contrib_velocity = 0
        recent_contribs = []
        for scan in prev_scans[-5:]:
            m = get_market_in_scan(scan, token, dex)
            if m:
                recent_contribs.append(m["contribution"])
        recent_contribs.append(current_contrib)

        if len(recent_contribs) >= 2:
            deltas = [recent_contribs[i+1] - recent_contribs[i] for i in range(len(recent_contribs)-1)]
            contrib_velocity = sum(deltas) / len(deltas)

            if contrib_velocity > 0.002 and len(recent_contribs) >= 3 and not alert_reasons:
                alert_reasons.append(f"VELOCITY +{contrib_velocity*100:.3f}%/scan sustained")

        if alert_reasons:
            contrib_history = []
            rank_history = []
            for scan in prev_scans[-5:]:
                m = get_market_in_scan(scan, token, dex)
                if m:
                    contrib_history.append(round(m["contribution"] * 100, 2))
                    rank_history.append(m["rank"])
                else:
                    contrib_history.append(None)
                    rank_history.append(None)
            contrib_history.append(round(current_contrib * 100, 2))
            rank_history.append(current_rank)

            dir_label = market["direction"].upper()

            # Determine max leverage from file-based cache
            lev_key = f"xyz:{token}" if dex else token
            alert_max_lev = MAX_LEV_DATA.get(lev_key) or MAX_LEV_DATA.get(token)

            # Qualified asset name (includes xyz: prefix for equities)
            qualified_asset = f"xyz:{token}" if dex == "xyz" else token

            # Map signal type to conviction
            if is_first_jump:
                alert_conviction = SIGNAL_CONVICTION["FIRST_JUMP"]
            elif is_contrib_explosion:
                alert_conviction = SIGNAL_CONVICTION["CONTRIB_EXPLOSION"]
            elif is_immediate:
                alert_conviction = SIGNAL_CONVICTION["IMMEDIATE_MOVER"]
            elif is_deep_climber and any("NEW_ENTRY_DEEP" in r for r in alert_reasons):
                alert_conviction = SIGNAL_CONVICTION["NEW_ENTRY_DEEP"]
            elif is_deep_climber:
                alert_conviction = SIGNAL_CONVICTION["DEEP_CLIMBER"]
            else:
                alert_conviction = 0.5

            # Signal type label + numeric priority (1=highest)
            if is_first_jump:
                signal_type, signal_priority = "FIRST_JUMP", 1
            elif is_contrib_explosion:
                signal_type, signal_priority = "CONTRIB_EXPLOSION", 2
            elif is_immediate:
                signal_type, signal_priority = "IMMEDIATE_MOVER", 3
            elif is_deep_climber and any("NEW_ENTRY_DEEP" in r for r in alert_reasons):
                signal_type, signal_priority = "NEW_ENTRY_DEEP", 4
            else:
                signal_type, signal_priority = "DEEP_CLIMBER", 5

            alerts.append({
                "token": token,
                "dex": dex if dex else None,
                "qualifiedAsset": qualified_asset,
                "signal": f"{token} {dir_label}",
                "direction": dir_label,
                "currentRank": current_rank,
                "contribution": round(current_contrib * 100, 3),
                "contribVelocity": round(contrib_velocity * 100, 4),
                "traders": market["traders"],
                "priceChg4h": market["price_chg_4h"],
                "maxLeverage": alert_max_lev,
                "conviction": alert_conviction,
                "signalType": signal_type,
                "signalPriority": signal_priority,
                "reasons": alert_reasons,
                "reasonCount": len(alert_reasons),
                "rankHistory": rank_history,
                "contribHistory": contrib_history,
                "isDeepClimber": is_deep_climber,
                "isImmediate": is_immediate,
                "isFirstJump": is_first_jump,
                "isContribExplosion": is_contrib_explosion,
                "rankJumpThisScan": rank_jump_this_scan
            })

# ─── Erratic + velocity filters ───
def is_erratic_history(rank_history, exclude_last=False):
    """Detect zigzag rank patterns."""
    nums = [r for r in rank_history if r is not None]
    if exclude_last and len(nums) > 1:
        nums = nums[:-1]
    if len(nums) < 3:
        return False
    for i in range(1, len(nums) - 1):
        prev_delta = nums[i] - nums[i-1]
        next_delta = nums[i+1] - nums[i]
        if prev_delta < 0 and next_delta > ERRATIC_REVERSAL_THRESHOLD:
            return True
        if prev_delta > 0 and next_delta < -ERRATIC_REVERSAL_THRESHOLD:
            return True
    return False

for alert in alerts:
    rh = alert.get("rankHistory", [])
    vel = alert.get("contribVelocity", 0)
    is_imm = alert.get("isImmediate", False)
    is_fj = alert.get("isFirstJump", False)
    is_ce = alert.get("isContribExplosion", False)
    big_jump = alert.get("rankJumpThisScan", 0) >= 10

    if is_ce:
        erratic = False
    elif big_jump or is_fj:
        erratic = is_erratic_history(rh, exclude_last=True)
    else:
        erratic = is_erratic_history(rh, exclude_last=False)

    if is_imm or is_fj:
        low_vel = vel <= 0
    else:
        low_vel = vel < (MIN_VELOCITY_FOR_DEEP_CLIMBER * 100)

    alert["erratic"] = erratic
    alert["lowVelocity"] = low_vel

    # Downgrade logic
    if is_fj:
        pass
    elif is_ce:
        pass
    elif is_imm and (erratic or low_vel):
        alert["isImmediate"] = False
        alert["signalType"] = "DEEP_CLIMBER"
        alert["signalPriority"] = 5
        alert["conviction"] = SIGNAL_CONVICTION["DEEP_CLIMBER"]
        if erratic:
            alert["reasons"].append("DOWNGRADED: erratic rank history (zigzag in pre-jump history)")
        if low_vel:
            alert["reasons"].append(f"DOWNGRADED: non-positive velocity ({alert['contribVelocity']:.4f})")
    elif not is_imm and alert.get("isDeepClimber") and low_vel:
        alert["reasons"].append(f"LOW_VEL: velocity {alert['contribVelocity']:.4f} < 0.03 for DEEP_CLIMBER")

# ─── FOX Scoring (in script, not mandate) ───
def compute_fox_score(alert):
    """Compute FOX score for an alert. Returns integer score."""
    score = 0
    if alert.get("isFirstJump"):
        score += 3
    if alert.get("isImmediate") and not alert.get("isFirstJump"):
        score += 2
    if alert.get("contribVelocity", 0) > 10:
        score += 2
    if alert.get("isContribExplosion"):
        score += 2
    if alert.get("isDeepClimber") and not alert.get("isImmediate") and not alert.get("isFirstJump"):
        score += 1
    # Other reasons: +1 each for RANK_UP, CLIMBING, ACCEL, STREAK, NEW_ENTRY, VELOCITY
    scored_prefixes = {"RANK_UP", "CLIMBING", "ACCEL", "STREAK", "NEW_ENTRY", "VELOCITY"}
    for reason in alert.get("reasons", []):
        for prefix in scored_prefixes:
            if reason.startswith(prefix):
                score += 1
                break
    # BTC alignment: check if market regime aligns with direction
    if MARKET_REGIME == "BULLISH" and alert.get("direction") == "LONG":
        score += 1
    elif MARKET_REGIME == "BEARISH" and alert.get("direction") == "SHORT":
        score += 1
    return score

for alert in alerts:
    alert["score"] = compute_fox_score(alert)

# ─── Re-entry detection ───
def check_reentry_candidates(alerts):
    """Check recently-deactivated DSL states for Phase 1 exits within 2h.
    If asset still in scanner with same direction, mark as re-entry candidate."""
    scan_now = datetime.now(timezone.utc)
    all_strategies = {}
    try:
        all_strategies = load_all_strategies()
    except Exception:
        return

    alert_map = {a["token"]: a for a in alerts}

    for key, cfg in all_strategies.items():
        import glob as globmod
        for sf in globmod.glob(dsl_state_glob(key)):
            try:
                with open(sf) as f:
                    state = json.load(f)
                # Only check recently-deactivated Phase 1 exits
                if state.get("active"):
                    continue
                if state.get("phase", 0) != 1:
                    continue
                deactivated_at = state.get("deactivatedAt") or state.get("closedAt")
                if not deactivated_at:
                    continue
                deact_time = datetime.fromisoformat(deactivated_at.replace("Z", "+00:00"))
                age_min = (scan_now - deact_time).total_seconds() / 60
                if age_min > REENTRY_WINDOW_MINUTES:
                    continue

                # Check ROE loss
                roe_loss = abs(float(state.get("exitROE", state.get("lastROE", 0)) or 0))
                if roe_loss > REENTRY_MAX_LOSS_ROE:
                    continue

                asset = state.get("asset", "")
                direction = state.get("direction", "")

                # Check if this asset is still in scanner with same direction
                matching_alert = alert_map.get(asset)
                if not matching_alert:
                    continue
                if matching_alert["direction"] != direction:
                    continue
                if matching_alert.get("contribVelocity", 0) <= REENTRY_MIN_VELOCITY:
                    continue

                # Mark as re-entry
                matching_alert["isReentry"] = True
                matching_alert["reentryOf"] = asset
                matching_alert["_reentryScoreThreshold"] = REENTRY_SCORE_THRESHOLD
            except (json.JSONDecodeError, IOError, KeyError, ValueError, TypeError, AttributeError):
                continue

check_reentry_candidates(alerts)

# ─── Save history ───
history["scans"].append(current_scan)
if len(history["scans"]) > MAX_HISTORY:
    history["scans"] = history["scans"][-MAX_HISTORY:]

atomic_write(HISTORY_FILE, history)

# ─── Sort: priority number (1=highest) > velocity > reason count ───
alerts.sort(key=lambda a: (
    a.get("signalPriority", 99),
    -abs(a.get("contribVelocity", 0)),
    -len(a["reasons"])
))

for idx, alert in enumerate(alerts):
    alert["signalIndex"] = idx

# ─── Slot availability per strategy (clearinghouse-backed) ───
import glob as globmod

APPROX_GRACE_MINUTES = 10

strategy_slots = {}
try:
    all_strategies = load_all_strategies()
    for key, cfg in all_strategies.items():
        max_slots = cfg.get("slots", 2)
        wallet = cfg.get("wallet", "")

        # Count DSL state files with active=True, excluding stale approximate DSLs
        dsl_active_count = count_active_dsls(dsl_state_glob(key), approx_grace_minutes=APPROX_GRACE_MINUTES)
        slot_ages = []
        rotation_eligible_coins = []
        scan_now = datetime.now(timezone.utc)
        for sf in globmod.glob(dsl_state_glob(key)):
            try:
                with open(sf) as f:
                    s = json.load(f)
                if not s.get("active"):
                    continue
                coin_name = s.get("asset", os.path.basename(sf).replace("dsl-", "").replace(".json", ""))
                slot_age_min = None
                if s.get("createdAt"):
                    try:
                        created = datetime.fromisoformat(s["createdAt"].replace("Z", "+00:00"))
                        slot_age_min = round((scan_now - created).total_seconds() / 60, 1)
                    except (ValueError, TypeError):
                        pass
                slot_ages.append({"coin": coin_name, "ageMinutes": slot_age_min})
                if slot_age_min is None or slot_age_min >= ROTATION_COOLDOWN_MINUTES:
                    rotation_eligible_coins.append(coin_name)
            except (json.JSONDecodeError, IOError, KeyError, AttributeError):
                continue

        # Cross-check against on-chain positions
        on_chain_count = 0
        on_chain_coins = []
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
                        coin = pos.get("coin", "")
                        szi = float(pos.get("szi", 0))
                        if coin and szi != 0:
                            on_chain_count += 1
                            on_chain_coins.append(coin)

        used = max(dsl_active_count, on_chain_count)

        strategy_slots[key] = {
            "name": cfg.get("name", key),
            "slots": max_slots,
            "used": used,
            "available": max(0, max_slots - used),
            "dslActive": dsl_active_count,
            "onChain": on_chain_count,
            "onChainCoins": sorted(on_chain_coins) if on_chain_coins else [],
            "slotAges": slot_ages,
            "rotationEligibleCoins": sorted(rotation_eligible_coins),
            "rotationCooldownMinutes": ROTATION_COOLDOWN_MINUTES,
            "hasRotationCandidate": len(rotation_eligible_coins) > 0,
        }
except Exception:
    pass

any_slots_available = any(s["available"] > 0 for s in strategy_slots.values()) if strategy_slots else True

# ─── Pre-filter: no slots + no first jumps → clear alerts ───
has_first_jump = any(a.get("isFirstJump") for a in alerts)
any_rotation_candidate = any(
    s.get("hasRotationCandidate", True)
    for s in strategy_slots.values()
) if strategy_slots else True

if not any_slots_available and not has_first_jump:
    alerts = []
elif not any_slots_available and has_first_jump and not any_rotation_candidate:
    pass

# ─── Build topPicks with scoring + entry filters ───
def qualifies_for_entry(alert):
    """Apply FOX entry filters to determine if an alert qualifies."""
    score = alert.get("score", 0)
    max_lev = alert.get("maxLeverage")
    rank_jump = alert.get("rankJumpThisScan", 0)
    vel = alert.get("contribVelocity", 0)
    is_reentry = alert.get("isReentry", False)

    # Max leverage gate
    if max_lev is not None and max_lev < MIN_MAX_LEVERAGE:
        return False

    # Re-entry uses relaxed threshold
    if is_reentry:
        reentry_threshold = alert.get("_reentryScoreThreshold", REENTRY_SCORE_THRESHOLD)
        return score >= reentry_threshold

    # Rank jump minimum: rankJumpThisScan >= 15 OR contribVelocity > 15
    if rank_jump < MIN_RANK_JUMP and vel <= MIN_VELOCITY_OVERRIDE:
        return False

    # Score threshold (higher for NEUTRAL regime)
    threshold = SCORE_THRESHOLD_NEUTRAL if MARKET_REGIME == "NEUTRAL" else SCORE_THRESHOLD
    return score >= threshold

qualified_alerts = [a for a in alerts if qualifies_for_entry(a)]

total_available_slots = sum(s.get("available", 0) for s in strategy_slots.values())
first_jump_count = len([a for a in qualified_alerts if a.get("isFirstJump")])
pick_count = max(total_available_slots, first_jump_count)
top_picks = qualified_alerts[:pick_count] if pick_count > 0 else []

# Add entryCommands to each topPick
for pick in top_picks:
    pick["entryCommands"] = []
    # Find best-fit strategy
    for skey, sdata in strategy_slots.items():
        if sdata.get("available", 0) > 0 or (pick.get("isFirstJump") and sdata.get("hasRotationCandidate")):
            cmd = f"python3 {SCRIPTS_DIR}/fox-open-position.py --strategy {skey} --asset {pick['qualifiedAsset']} --signal-index {pick['signalIndex']}"
            pick["entryCommands"].append(cmd)
            break

# ─── Output ───
output = {
    "status": "ok",
    "time": now,
    "totalMarkets": len(current_scan["markets"]),
    "scansInHistory": len(history["scans"]),
    "marketRegime": MARKET_REGIME,
    "scoreThreshold": SCORE_THRESHOLD_NEUTRAL if MARKET_REGIME == "NEUTRAL" else SCORE_THRESHOLD,
    "strategySlots": strategy_slots,
    "anySlotsAvailable": any_slots_available,
    "totalAvailableSlots": total_available_slots,
    "topPicks": top_picks,
    "alerts": alerts,
    "firstJumps": [a for a in alerts if a.get("isFirstJump")],
    "immediateMovers": [a for a in alerts if a.get("isImmediate")],
    "contribExplosions": [a for a in alerts if a.get("isContribExplosion")],
    "deepClimbers": [a for a in alerts if a.get("isDeepClimber")],
    "hasFirstJump": any(a.get("isFirstJump") for a in alerts),
    "hasImmediate": any(a.get("isImmediate") for a in alerts),
    "hasContribExplosion": any(a.get("isContribExplosion") for a in alerts),
    "hasEmergingMover": len(alerts) > 0,
    "hasDeepClimber": any(a.get("isDeepClimber") for a in alerts),
}

print(json.dumps(output))

# Save output to file (prevents signal loss on re-run)
OUTPUT_FILE = os.path.join(os.path.dirname(HISTORY_FILE), "fox-emerging-movers-output.json")
atomic_write(OUTPUT_FILE, output)
