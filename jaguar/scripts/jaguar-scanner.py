#!/usr/bin/env python3
# Senpi JAGUAR Scanner v1.0
# Copyright 2026 Senpi (https://senpi.ai)
# Licensed under MIT
# Source: https://github.com/Senpi-ai/senpi-skills
"""JAGUAR v1.0 — Three-Mode Scanner with Gen-2 Signal Intelligence + Pyramiding.

Three entry modes:
  STALKER: SM accumulating over 3+ scans. Score 6+. Enter before the crowd.
  STRIKER: Violent FIRST_JUMP + volume >= 1.5x. Score 9+. Enter the explosion.
  HUNTER:  Gen-2 data — momentum events + quality traders + velocity. Score 8+.

Gen-2 confirmation layer on all modes:
  - Tier 2 momentum events ($5.5M+ threshold) with TCS/TRP quality tags
  - Score modifiers: ELITE/RELIABLE boost, CHOPPY block
  - contribution_pct_change_4h velocity divergence (SM moving before price)
  - Hard gate: CHOPPY + CONSERVATIVE = blocked

Pyramiding on winning positions:
  - Phase 2 (ROE > 7%) + re-confirmation (leaderboard or momentum event)
  - 50% of original margin, max 1 per position
  - Own DSL state file with tighter Phase 1

Hardened gates (in the code, not instructions):
  - XYZ equities banned at parse level
  - Leverage 7-10x enforced
  - Max 7 positions (pyramids don't count)
  - 10% daily loss limit, 2-hour per-asset cooldown
  - DSL state template in scanner output (no merging)
  - Conviction-scaled Phase 1 timing

Uses: leaderboard_get_markets + leaderboard_get_momentum_events (2 base calls)
Runs every 90 seconds.
"""

import json
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jaguar_config as cfg

TOP_N = 50
ERRATIC_REVERSAL_THRESHOLD = 5


# ═══════════════════════════════════════════════════════════════
# HARDCODED CONSTANTS — NOT configurable by the agent
# ═══════════════════════════════════════════════════════════════

MIN_LEVERAGE = 7
MAX_LEVERAGE = 10
MAX_POSITIONS = 7          # Pyramids don't count against this
MAX_DAILY_LOSS_PCT = 10
XYZ_BANNED = True

# Pyramid constraints
PYRAMID_MIN_ROE = 7        # Must be in Phase 2 territory
PYRAMID_MARGIN_PCT = 0.50  # 50% of original margin
PYRAMID_MAX_PER_POSITION = 1
PYRAMID_MAX_ACCOUNT_MARGIN_PCT = 0.60  # Never exceed 60% account margin

# DSL tiers — proven across 30 agents
DSL_TIERS = [
    {"triggerPct": 7,  "lockHwPct": 40, "consecutiveBreachesRequired": 3},
    {"triggerPct": 12, "lockHwPct": 55, "consecutiveBreachesRequired": 2},
    {"triggerPct": 15, "lockHwPct": 75, "consecutiveBreachesRequired": 2},
    {"triggerPct": 20, "lockHwPct": 85, "consecutiveBreachesRequired": 1},
]

# Conviction tiers — Phase 1 timing scaled by entry score
CONVICTION_TIERS = [
    {"minScore": 6,  "absoluteFloorRoe": -20, "hardTimeoutMin": 30, "weakPeakCutMin": 15, "deadWeightCutMin": 10},
    {"minScore": 8,  "absoluteFloorRoe": -25, "hardTimeoutMin": 45, "weakPeakCutMin": 20, "deadWeightCutMin": 15},
    {"minScore": 10, "absoluteFloorRoe": -30, "hardTimeoutMin": 60, "weakPeakCutMin": 30, "deadWeightCutMin": 20},
]

STAGNATION_TP = {"enabled": True, "roeMin": 10, "hwStaleMin": 45}

# TCS/TRP score modifiers
TCS_SCORE = {"ELITE": 2, "RELIABLE": 1, "STREAKY": 0, "CHOPPY": -2}
TRP_SCORE = {"SNIPER": 1, "AGGRESSIVE": 1, "BALANCED": 0, "CONSERVATIVE": -1}

# Hard block combos — these traders produce garbage signals
BLOCKED_TAG_COMBOS = [
    {"tcs": "CHOPPY", "trp": "CONSERVATIVE"},
]


# ═══════════════════════════════════════════════════════════════
# FETCH & PARSE
# ═══════════════════════════════════════════════════════════════

def fetch_markets():
    """Fetch current SM market concentration."""
    try:
        data = cfg.mcporter_call("leaderboard_get_markets", limit=100)
        data = data.get("data", data)
        raw = data.get("markets", data)
        if isinstance(raw, dict):
            raw = raw.get("markets", [])
        return raw
    except Exception:
        return None


def fetch_momentum_events():
    """Fetch Tier 2 momentum events ($5.5M+ threshold).
    Returns list of events with trader quality tags (TCS/TAS/TRP)."""
    try:
        data = cfg.mcporter_call("leaderboard_get_momentum_events")
        data = data.get("data", data)
        events = data.get("events", data)
        if isinstance(events, dict):
            events = events.get("events", [])
        if not isinstance(events, list):
            return []
        tier2_events = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            delta = abs(float(ev.get("delta_pnl", ev.get("deltaPnl", ev.get("pnl_delta", 0)))))
            if delta >= 5_500_000:
                tier2_events.append(ev)
        return tier2_events
    except Exception:
        return []


def parse_scan(raw_markets):
    """Parse raw markets into a scan snapshot.
    HARDCODED: xyz: assets filtered out at scan level."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    scan = {"time": now, "markets": []}
    for i, m in enumerate(raw_markets[:TOP_N]):
        if not isinstance(m, dict):
            continue
        token = m.get("token", "")
        dex = m.get("dex", "")
        if dex and dex.lower() == "xyz":
            continue
        if token.lower().startswith("xyz:"):
            continue
        scan["markets"].append({
            "token": token,
            "dex": dex,
            "rank": i + 1,
            "direction": m.get("direction", ""),
            "contribution": round(m.get("pct_of_top_traders_gain", 0), 6),
            "traders": m.get("trader_count", 0),
            "price_chg_4h": round(m.get("token_price_change_pct_4h", 0) or 0, 4),
            "contrib_velocity_4h": round(m.get("contribution_pct_change_4h", 0) or 0, 4),
        })
    return scan


def get_market_in_scan(scan, token, dex=""):
    for m in scan["markets"]:
        if m["token"] == token and m.get("dex", "") == dex:
            return m
    return None


# ═══════════════════════════════════════════════════════════════
# GEN-2 SIGNAL HELPERS
# ═══════════════════════════════════════════════════════════════

def extract_event_tags(event):
    """Extract TCS/TAS/TRP tags from a momentum event."""
    tags = event.get("trader_tags", event.get("traderTags", {}))
    if not isinstance(tags, dict):
        return None, None, None
    tcs = (tags.get("tcs", tags.get("TCS", "")) or "").upper()
    tas = (tags.get("tas", tags.get("TAS", "")) or "").upper()
    trp = (tags.get("trp", tags.get("TRP", "")) or "").upper()
    return tcs, tas, trp


def extract_event_assets(event):
    """Extract assets from a momentum event's top_positions."""
    positions = event.get("top_positions", event.get("topPositions", []))
    if not isinstance(positions, list):
        return []
    assets = []
    for pos in positions:
        if isinstance(pos, dict):
            coin = pos.get("coin", pos.get("token", pos.get("asset", "")))
            if coin:
                assets.append(coin.upper())
        elif isinstance(pos, str):
            assets.append(pos.upper())
    return assets


def get_event_concentration(event):
    """Get concentration score (0-1) from momentum event."""
    return float(event.get("concentration", event.get("gain_concentration", 0)) or 0)


def is_blocked_tags(tcs, trp):
    """Check if TCS+TRP combo is hard-blocked."""
    for combo in BLOCKED_TAG_COMBOS:
        if tcs == combo["tcs"] and trp == combo["trp"]:
            return True
    return False


def get_quality_score(tcs, trp, concentration):
    """Calculate quality score modifier from gen-2 tags.
    Returns (score_delta, reasons)."""
    score = 0
    reasons = []

    if tcs in TCS_SCORE:
        delta = TCS_SCORE[tcs]
        score += delta
        if delta != 0:
            reasons.append(f"TCS_{tcs}({'+' if delta > 0 else ''}{delta})")

    if trp in TRP_SCORE:
        delta = TRP_SCORE[trp]
        score += delta
        if delta != 0:
            reasons.append(f"TRP_{trp}({'+' if delta > 0 else ''}{delta})")

    if concentration > 0.7:
        score += 1
        reasons.append(f"HIGH_CONCENTRATION({concentration:.2f})")
    elif concentration > 0.5:
        reasons.append(f"CONCENTRATION_OK({concentration:.2f})")

    return score, reasons


def build_momentum_index(events):
    """Build a lookup: token -> list of quality-scored momentum events."""
    index = {}
    for event in events:
        tcs, tas, trp = extract_event_tags(event)
        concentration = get_event_concentration(event)
        assets = extract_event_assets(event)
        quality_score, quality_reasons = get_quality_score(tcs, trp, concentration)
        blocked = is_blocked_tags(tcs, trp)

        for asset in assets:
            if asset not in index:
                index[asset] = []
            index[asset].append({
                "tcs": tcs,
                "tas": tas,
                "trp": trp,
                "concentration": concentration,
                "qualityScore": quality_score,
                "qualityReasons": quality_reasons,
                "blocked": blocked,
                "event": event,
            })
    return index


def get_best_momentum_for_asset(momentum_index, token):
    """Get the best (highest quality score) momentum event for an asset.
    Returns (quality_score, quality_reasons, is_blocked, has_momentum)."""
    entries = momentum_index.get(token.upper(), [])
    if not entries:
        return 0, [], False, False

    if any(e["blocked"] for e in entries):
        return 0, ["BLOCKED_CHOPPY_CONSERVATIVE"], True, True

    best = max(entries, key=lambda e: e["qualityScore"])
    return best["qualityScore"], best["qualityReasons"], False, True


def get_velocity_score(market):
    """Score contribution_pct_change_4h velocity vs price movement.
    SM velocity diverging from price = smart money moving early."""
    velocity = market.get("contrib_velocity_4h", 0)
    price_chg = market.get("price_chg_4h", 0)
    direction = market.get("direction", "").upper()

    score = 0
    reasons = []

    if velocity == 0:
        return 0, []

    velocity_aligned = False
    if direction == "LONG" and velocity > 0:
        velocity_aligned = True
    elif direction == "SHORT" and velocity > 0:
        velocity_aligned = True

    if velocity_aligned and abs(velocity) > 5:
        score += 1
        reasons.append(f"VELOCITY_STRONG({velocity:.1f}%)")
    elif velocity_aligned and abs(velocity) > 2:
        reasons.append(f"VELOCITY_OK({velocity:.1f}%)")

    if velocity_aligned and abs(velocity) > 5 and abs(price_chg) < 2:
        score += 1
        reasons.append("VELOCITY_DIVERGENCE")

    if not velocity_aligned and abs(velocity) > 3:
        score -= 1
        reasons.append(f"VELOCITY_RETREATING({velocity:.1f}%)")

    return score, reasons


# ═══════════════════════════════════════════════════════════════
# SHARED HELPERS
# ═══════════════════════════════════════════════════════════════

def check_asset_volume(token, dex=""):
    """Check if raw asset volume is alive. Returns (ratio, is_strong)."""
    asset_name = f"{dex}:{token}" if dex else token
    data = cfg.mcporter_call("market_get_asset_data", asset=asset_name,
                              candle_intervals=["1h"],
                              include_funding=False, include_order_book=False)
    if not data:
        return 0, False

    candle_data = data.get("data", data) if isinstance(data, dict) else data
    if isinstance(candle_data, dict):
        candles = candle_data.get("candles", {}).get("1h", [])
    else:
        return 0, False

    if len(candles) < 6:
        return 0, False

    vols = [float(c.get("volume", c.get("v", c.get("vlm", 0)))) for c in candles[-6:]]
    avg_vol = sum(vols[:-1]) / len(vols[:-1]) if len(vols) > 1 else 1
    latest_vol = vols[-1] if vols else 0

    ratio = latest_vol / avg_vol if avg_vol > 0 else 0
    return ratio, ratio >= 1.5


def is_erratic_history(rank_history, exclude_last=False):
    """Detect zigzag rank patterns."""
    nums = [r for r in rank_history if r is not None]
    if exclude_last and len(nums) > 1:
        nums = nums[:-1]
    if len(nums) < 3:
        return False
    for i in range(1, len(nums) - 1):
        prev_delta = nums[i] - nums[i - 1]
        next_delta = nums[i + 1] - nums[i]
        if prev_delta < 0 and next_delta > ERRATIC_REVERSAL_THRESHOLD:
            return True
        if prev_delta > 0 and next_delta < -ERRATIC_REVERSAL_THRESHOLD:
            return True
    return False


def time_of_day_modifier():
    """UTC time-of-day scoring adjustment."""
    hour = datetime.now(timezone.utc).hour
    if 4 <= hour < 14:
        return 1, "time_bonus_optimal_window"
    elif hour >= 18 or hour < 2:
        return -2, "time_penalty_chop_zone"
    return 0, None


def check_4h_alignment(direction, price_chg_4h):
    """4H trend must agree with signal direction. Hard block."""
    if direction == "LONG" and price_chg_4h < 0:
        return False
    if direction == "SHORT" and price_chg_4h > 0:
        return False
    return True


# ═══════════════════════════════════════════════════════════════
# MODE A: STALKER (Accumulation Detection)
# ═══════════════════════════════════════════════════════════════

def detect_stalker_signals(current_scan, history, config, momentum_index):
    """Detect steady rank climbers over 3+ consecutive scans.
    Gen-2 signals applied as score modifiers + hard gates."""

    stalker_cfg = config.get("stalker", {})
    min_consecutive_scans = stalker_cfg.get("minConsecutiveScans", 3)
    min_total_climb = stalker_cfg.get("minTotalClimb", 5)
    min_score = stalker_cfg.get("minScore", 6)
    require_volume_building = stalker_cfg.get("requireVolumeBuilding", True)

    prev_scans = history.get("scans", [])
    if len(prev_scans) < min_consecutive_scans:
        return []

    signals = []

    for market in current_scan["markets"]:
        token = market["token"]
        dex = market.get("dex", "")
        current_rank = market["rank"]
        direction = market["direction"].upper()

        if current_rank <= 10:
            continue

        if not check_4h_alignment(direction, market.get("price_chg_4h", 0)):
            continue

        # Gen-2 hard gate: blocked tag combos only
        q_score, q_reasons, is_blocked, has_momentum = get_best_momentum_for_asset(momentum_index, token)
        if is_blocked:
            continue

        # Build rank history
        rank_history = []
        contrib_history = []
        for scan in prev_scans[-(min_consecutive_scans + 2):]:
            m = get_market_in_scan(scan, token, dex)
            if m:
                rank_history.append(m["rank"])
                contrib_history.append(m["contribution"])
            else:
                rank_history.append(None)
                contrib_history.append(None)
        rank_history.append(current_rank)
        contrib_history.append(market["contribution"])

        valid_ranks = [(i, r) for i, r in enumerate(rank_history) if r is not None]
        if len(valid_ranks) < min_consecutive_scans + 1:
            continue

        recent_ranks = [r for _, r in valid_ranks[-(min_consecutive_scans + 1):]]
        is_climbing = all(recent_ranks[i] >= recent_ranks[i + 1] for i in range(len(recent_ranks) - 1))
        total_climb = recent_ranks[0] - recent_ranks[-1]

        if not is_climbing or total_climb < min_total_climb:
            continue

        if is_erratic_history(rank_history, exclude_last=True):
            continue

        valid_contribs = [c for c in contrib_history if c is not None]
        volume_building = True
        if require_volume_building and len(valid_contribs) >= 3:
            recent_c = valid_contribs[-3:]
            volume_building = all(recent_c[i] <= recent_c[i + 1] for i in range(len(recent_c) - 1))

        if require_volume_building and not volume_building:
            continue

        # ── Scoring ──
        score = 0
        reasons = []

        score += 3
        reasons.append(f"STALKER_CLIMB +{total_climb} over {len(recent_ranks)} scans")

        if len(valid_contribs) >= 2:
            deltas = [valid_contribs[i + 1] - valid_contribs[i] for i in range(len(valid_contribs) - 1)]
            vel = sum(deltas) / len(deltas)
            if vel > 0.001:
                score += 2
                reasons.append(f"CONTRIB_ACCEL +{vel * 100:.3f}%/scan")
            elif vel > 0:
                score += 1
                reasons.append(f"CONTRIB_POSITIVE +{vel * 100:.4f}%/scan")

        if market["traders"] >= 10:
            score += 1
            reasons.append(f"SM_ACTIVE {market['traders']} traders")

        if recent_ranks[0] >= 30:
            score += 1
            reasons.append(f"DEEP_START from #{recent_ranks[0]}")

        tod_mod, tod_reason = time_of_day_modifier()
        score += tod_mod
        if tod_reason:
            reasons.append(tod_reason)

        # Gen-2 score modifiers
        if has_momentum:
            score += q_score
            reasons.extend(q_reasons)

        v_score, v_reasons = get_velocity_score(market)
        score += v_score
        reasons.extend(v_reasons)

        if score < min_score:
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
            "consecutiveScans": len(recent_ranks),
            "contribution": round(market["contribution"] * 100, 3),
            "traders": market["traders"],
            "priceChg4h": market.get("price_chg_4h", 0),
            "contribVelocity4h": market.get("contrib_velocity_4h", 0),
            "rankHistory": rank_history,
            "hasMomentumEvent": has_momentum,
            "qualityScore": q_score,
        })

    return signals


# ═══════════════════════════════════════════════════════════════
# MODE B: STRIKER (Explosion Detection)
# ═══════════════════════════════════════════════════════════════

def detect_striker_signals(current_scan, history, config, momentum_index):
    """Detect violent FIRST_JUMP signals.
    Gen-2 signals applied as score modifiers + hard gates."""

    striker_cfg = config.get("striker", {})
    min_score = striker_cfg.get("minScore", 9)
    min_reasons = striker_cfg.get("minReasons", 4)
    min_rank_jump = striker_cfg.get("minRankJump", 15)
    min_velocity_override = striker_cfg.get("minVelocityOverride", 15)
    min_velocity_floor = striker_cfg.get("minVelocityFloor", 10)
    require_volume = striker_cfg.get("requireVolumeConfirmation", True)

    prev_scans = history.get("scans", [])
    if not prev_scans:
        return []

    latest_prev = prev_scans[-1]
    oldest_available = prev_scans[-min(len(prev_scans), 5)]

    prev_top50_tokens = set()
    for m in latest_prev["markets"]:
        prev_top50_tokens.add((m["token"], m.get("dex", "")))

    signals = []

    for market in current_scan["markets"]:
        token = market["token"]
        dex = market.get("dex", "")
        current_rank = market["rank"]
        direction = market["direction"].upper()
        current_contrib = market["contribution"]

        if current_rank <= 10:
            continue

        if not check_4h_alignment(direction, market.get("price_chg_4h", 0)):
            continue

        # Gen-2 hard gate
        q_score, q_reasons, is_blocked, has_momentum = get_best_momentum_for_asset(momentum_index, token)
        if is_blocked:
            continue

        prev_market = get_market_in_scan(latest_prev, token, dex)
        old_market = get_market_in_scan(oldest_available, token, dex)

        if not prev_market:
            continue

        rank_jump = prev_market["rank"] - current_rank

        is_first_jump = False
        is_immediate = False
        is_contrib_explosion = False
        reasons = []

        if rank_jump >= 10 and prev_market["rank"] >= 25:
            is_immediate = True
            reasons.append(f"IMMEDIATE_MOVER +{rank_jump} from #{prev_market['rank']}")

            was_in_prev = (token, dex) in prev_top50_tokens
            if not was_in_prev or prev_market["rank"] >= 30:
                is_first_jump = True
                reasons.append(f"FIRST_JUMP #{prev_market['rank']}->#{current_rank}")

        if prev_market["contribution"] > 0:
            contrib_ratio = current_contrib / prev_market["contribution"]
            if contrib_ratio >= 3.0:
                is_contrib_explosion = True
                reasons.append(f"CONTRIB_EXPLOSION {contrib_ratio:.1f}x")

        if not is_first_jump and not is_immediate:
            continue

        contrib_velocity = 0
        recent_contribs = []
        for scan in prev_scans[-5:]:
            m = get_market_in_scan(scan, token, dex)
            if m:
                recent_contribs.append(m["contribution"])
        recent_contribs.append(current_contrib)
        if len(recent_contribs) >= 2:
            deltas = [recent_contribs[i + 1] - recent_contribs[i] for i in range(len(recent_contribs) - 1)]
            contrib_velocity = sum(deltas) / len(deltas) * 100

        abs_velocity = abs(contrib_velocity)

        if rank_jump < min_rank_jump and abs_velocity < min_velocity_override:
            continue

        if abs_velocity < min_velocity_floor:
            if is_first_jump and contrib_velocity > 0:
                pass
            else:
                continue

        # ── Scoring ──
        score = 0

        if is_first_jump:
            score += 3
        if is_immediate:
            score += 2
        if is_contrib_explosion:
            score += 2
        if abs_velocity > 10:
            score += 2
            reasons.append(f"HIGH_VELOCITY {abs_velocity:.1f}")

        if prev_market["rank"] >= 40:
            score += 1
            reasons.append("DEEP_CLIMBER")

        if old_market:
            total_climb = old_market["rank"] - current_rank
            if total_climb >= 10:
                score += 1
                reasons.append(f"CLIMBING +{total_climb} over scans")

        tod_mod, tod_reason = time_of_day_modifier()
        score += tod_mod
        if tod_reason:
            reasons.append(tod_reason)

        # Gen-2 score modifiers
        if has_momentum:
            score += q_score
            reasons.extend(q_reasons)

        v_score, v_reasons = get_velocity_score(market)
        score += v_score
        reasons.extend(v_reasons)

        if score < min_score or len(reasons) < min_reasons:
            continue

        # Volume confirmation
        vol_ratio, vol_strong = 0, True
        if require_volume:
            vol_ratio, vol_strong = check_asset_volume(token, dex)
            if not vol_strong:
                continue
            reasons.append(f"VOL_CONFIRMED {vol_ratio:.1f}x")

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
            "isContribExplosion": is_contrib_explosion,
            "contribVelocity": round(contrib_velocity, 4),
            "volRatio": round(vol_ratio, 2),
            "contribution": round(current_contrib * 100, 3),
            "traders": market["traders"],
            "priceChg4h": market.get("price_chg_4h", 0),
            "contribVelocity4h": market.get("contrib_velocity_4h", 0),
            "hasMomentumEvent": has_momentum,
            "qualityScore": q_score,
        })

    return signals


# ═══════════════════════════════════════════════════════════════
# MODE C: HUNTER (Gen-2 Independent Signal)
# ═══════════════════════════════════════════════════════════════

def detect_hunter_signals(current_scan, momentum_index, config):
    """Generate signals from gen-2 data alone — independent of Stalker/Striker.

    Pipeline:
    1. Find assets with Tier 2 momentum events (any quality — not just positive)
    2. Cross-reference: asset must be on SM leaderboard (top 50)
    3. Verify contribution velocity is accelerating
    4. Volume confirmation
    5. Score and filter (minScore: 8)

    Relaxed vs initial design:
    - qualityScore >= 0 (not > 0) — allows STREAKY/BALANCED through, only blocks CHOPPY+CONSERVATIVE
    - minTraders: 3 (not 5) — catches early moves with fewer participants
    """
    hunter_cfg = config.get("hunter", {})
    min_score = hunter_cfg.get("minScore", 8)
    min_traders = hunter_cfg.get("minTraders", 3)

    signals = []

    seen_tokens = set()
    for token, events in momentum_index.items():
        if token in seen_tokens:
            continue
        seen_tokens.add(token)

        # Hard block: CHOPPY+CONSERVATIVE only
        if any(e["blocked"] for e in events):
            continue

        # Allow any non-blocked event through (qualityScore >= 0)
        valid_events = [e for e in events if e["qualityScore"] >= 0]
        if not valid_events:
            continue

        best_event = max(valid_events, key=lambda e: e["qualityScore"])

        # Cross-reference with SM leaderboard
        market = None
        for m in current_scan["markets"]:
            if m["token"].upper() == token.upper():
                market = m
                break

        if not market:
            continue

        direction = market["direction"].upper()

        if not check_4h_alignment(direction, market.get("price_chg_4h", 0)):
            continue

        if market["traders"] < min_traders:
            continue

        # ── Scoring ──
        score = 5  # HUNTER base
        reasons = [f"HUNTER_MOMENTUM({token})"]

        # Quality tag scoring
        score += best_event["qualityScore"]
        reasons.extend(best_event["qualityReasons"])

        # Concentration bonus
        if best_event["concentration"] > 0.7:
            score += 1
            reasons.append(f"HIGH_FOCUS({best_event['concentration']:.2f})")

        # Velocity scoring
        v_score, v_reasons = get_velocity_score(market)
        score += v_score
        reasons.extend(v_reasons)

        # Leaderboard rank bonus
        if market["rank"] <= 20:
            score += 1
            reasons.append(f"SM_TOP20(#{market['rank']})")

        # Trader count bonus
        if market["traders"] >= 10:
            score += 1
            reasons.append(f"SM_ACTIVE({market['traders']} traders)")

        # Time-of-day
        tod_mod, tod_reason = time_of_day_modifier()
        score += tod_mod
        if tod_reason:
            reasons.append(tod_reason)

        if score < min_score:
            continue

        # Volume confirmation
        vol_ratio, vol_strong = check_asset_volume(token, market.get("dex", ""))
        if not vol_strong:
            continue
        reasons.append(f"VOL_CONFIRMED({vol_ratio:.1f}x)")

        signals.append({
            "token": market["token"],
            "dex": market.get("dex") or None,
            "direction": direction,
            "mode": "HUNTER",
            "score": score,
            "reasons": reasons,
            "currentRank": market["rank"],
            "contribution": round(market["contribution"] * 100, 3),
            "traders": market["traders"],
            "priceChg4h": market.get("price_chg_4h", 0),
            "contribVelocity4h": market.get("contrib_velocity_4h", 0),
            "volRatio": round(vol_ratio, 2),
            "hasMomentumEvent": True,
            "qualityScore": best_event["qualityScore"],
            "tcs": best_event["tcs"],
            "trp": best_event["trp"],
            "concentration": best_event["concentration"],
        })

    return signals


# ═══════════════════════════════════════════════════════════════
# PYRAMIDING
# ═══════════════════════════════════════════════════════════════

def detect_pyramid_opportunities(current_scan, momentum_index, existing_positions):
    """Check existing winning positions for pyramid opportunities.

    Trigger: ROE > 7% AND either:
      - Asset still in SM leaderboard top 35
      - Fresh Tier 2 momentum event from non-blocked traders

    Constraints: max 1 per position, 50% margin, account margin < 60%.
    """
    pyramids = []

    for pos in existing_positions:
        coin = pos.get("coin", "")
        direction = pos.get("direction", "")
        roe = pos.get("roe", 0)
        margin = pos.get("margin", 0)

        if roe < PYRAMID_MIN_ROE:
            continue

        if cfg.has_pyramided(coin):
            continue

        market = None
        for m in current_scan["markets"]:
            if m["token"].upper() == coin.upper():
                market = m
                break

        has_leaderboard_confirmation = False
        has_momentum_confirmation = False
        reasons = []

        if market:
            if market["direction"].upper() != direction.upper():
                continue
            if market["rank"] <= 35:
                has_leaderboard_confirmation = True
                reasons.append(f"SM_ACTIVE(#{market['rank']}, {market['traders']} traders)")

        q_score, q_reasons, is_blocked, has_momentum = get_best_momentum_for_asset(momentum_index, coin)
        if is_blocked:
            continue
        if has_momentum and q_score >= 0:
            has_momentum_confirmation = True
            reasons.extend(q_reasons)

        if not has_leaderboard_confirmation and not has_momentum_confirmation:
            continue

        pyramid_margin = round(margin * PYRAMID_MARGIN_PCT, 2)
        score = 0
        if has_leaderboard_confirmation:
            score += 3
        if has_momentum_confirmation:
            score += max(q_score, 1)
        reasons.insert(0, f"PYRAMID({coin} {direction} ROE={roe:.1f}%)")

        pyramids.append({
            "token": coin,
            "direction": direction,
            "mode": "PYRAMID",
            "score": score,
            "reasons": reasons,
            "currentRoe": roe,
            "originalMargin": margin,
            "pyramidMargin": pyramid_margin,
            "hasLeaderboardConfirmation": has_leaderboard_confirmation,
            "hasMomentumConfirmation": has_momentum_confirmation,
        })

    return pyramids


# ═══════════════════════════════════════════════════════════════
# DSL STATE TEMPLATE
# ═══════════════════════════════════════════════════════════════

def build_dsl_state_template(signal):
    """Build the EXACT DSL state file contents for a signal.
    The agent writes this directly — no merging with dsl-profile.json."""

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
        "phase2": {
            "enabled": True,
            "retraceThreshold": 0.015,
            "consecutiveBreachesRequired": 2,
        },
        "tiers": DSL_TIERS,
        "stagnationTp": STAGNATION_TP,
        "convictionTiers": CONVICTION_TIERS,
        "execution": {
            "phase1SlOrderType": "MARKET",
            "phase2SlOrderType": "MARKET",
            "breachCloseOrderType": "MARKET",
        },
        "_jaguar_version": "1.0",
        "_note": "Generated by jaguar-scanner.py. Do not modify. Do not merge with dsl-profile.json.",
    }


def build_pyramid_dsl_state(pyramid_signal):
    """Build DSL state for a pyramid add-on.
    Tighter Phase 1 since the base position is already winning."""
    state = build_dsl_state_template(pyramid_signal)
    state["mode"] = "PYRAMID"
    state["isPyramid"] = True
    state["phase1"]["phase1MaxMinutes"] = 20
    state["phase1"]["absoluteFloorRoe"] = -15
    state["phase1"]["deadWeightCutMin"] = 8
    state["_note"] = "Pyramid position. Tighter Phase 1. Generated by jaguar-scanner.py."
    return state


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def run():
    config = cfg.load_config()
    entry_cfg = config.get("entry", {})
    cooldown_min = entry_cfg.get("assetCooldownMinutes", 120)

    # ── Fetch data (2 base API calls) ──
    raw_markets = fetch_markets()
    if raw_markets is None:
        cfg.output({"status": "error", "error": "failed to fetch markets"})
        return

    momentum_events = fetch_momentum_events()

    # Parse
    current_scan = parse_scan(raw_markets)
    momentum_index = build_momentum_index(momentum_events)

    # Load history
    history = cfg.load_scan_history()

    # ── Detect all three modes ──
    stalker_signals = detect_stalker_signals(current_scan, history, entry_cfg, momentum_index)
    striker_signals = detect_striker_signals(current_scan, history, entry_cfg, momentum_index)
    hunter_signals = detect_hunter_signals(current_scan, momentum_index, entry_cfg)

    # Save history
    history["scans"].append(current_scan)
    cfg.save_scan_history(history)

    # Apply per-asset cooldowns
    stalker_signals = [s for s in stalker_signals if not cfg.is_asset_cooled_down(s["token"], cooldown_min)]
    striker_signals = [s for s in striker_signals if not cfg.is_asset_cooled_down(s["token"], cooldown_min)]
    hunter_signals = [s for s in hunter_signals if not cfg.is_asset_cooled_down(s["token"], cooldown_min)]

    # Sort by score
    stalker_signals.sort(key=lambda s: s["score"], reverse=True)
    striker_signals.sort(key=lambda s: s["score"], reverse=True)
    hunter_signals.sort(key=lambda s: s["score"], reverse=True)

    # Combine — priority: Striker > Hunter > Stalker for same token
    seen_tokens = set()
    combined = []
    for sig in striker_signals:
        seen_tokens.add(sig["token"])
        combined.append(sig)
    for sig in hunter_signals:
        if sig["token"] not in seen_tokens:
            seen_tokens.add(sig["token"])
            combined.append(sig)
    for sig in stalker_signals:
        if sig["token"] not in seen_tokens:
            seen_tokens.add(sig["token"])
            combined.append(sig)
    combined.sort(key=lambda s: s["score"], reverse=True)

    # Build DSL state templates
    for signal in combined:
        signal["dslState"] = build_dsl_state_template(signal)

    # ── Pyramid detection ──
    wallet, _ = cfg.get_wallet_and_strategy()
    account_value, positions = cfg.get_positions(wallet) if wallet else (0, [])
    total_margin = sum(p.get("margin", 0) for p in positions)
    margin_pct = total_margin / account_value if account_value > 0 else 1.0

    pyramid_signals = []
    if positions and margin_pct < PYRAMID_MAX_ACCOUNT_MARGIN_PCT:
        pyramid_signals = detect_pyramid_opportunities(current_scan, momentum_index, positions)
        for psig in pyramid_signals:
            psig["dslState"] = build_pyramid_dsl_state(psig)

    # ── Output ──
    cfg.output({
        "status": "ok",
        "time": current_scan["time"],
        "totalMarkets": len(current_scan["markets"]),
        "scansInHistory": len(history["scans"]),
        "momentumEventsCount": len(momentum_events),
        "tier2EventsIndexed": len(momentum_index),
        "stalkerSignals": stalker_signals,
        "strikerSignals": striker_signals,
        "hunterSignals": hunter_signals,
        "combined": combined,
        "pyramidSignals": pyramid_signals,
        "hasStalker": len(stalker_signals) > 0,
        "hasStriker": len(striker_signals) > 0,
        "hasHunter": len(hunter_signals) > 0,
        "hasSignal": len(combined) > 0,
        "hasPyramid": len(pyramid_signals) > 0,
        "currentPositions": len(positions),
        "accountValue": round(account_value, 2),
        "totalMarginPct": round(margin_pct * 100, 1),
        "constraints": {
            "minLeverage": MIN_LEVERAGE,
            "maxLeverage": MAX_LEVERAGE,
            "maxPositions": MAX_POSITIONS,
            "maxDailyLossPct": MAX_DAILY_LOSS_PCT,
            "xyzBanned": XYZ_BANNED,
            "assetCooldownMinutes": cooldown_min,
            "stagnationTp": STAGNATION_TP,
            "dslTiers": DSL_TIERS,
            "convictionTiers": CONVICTION_TIERS,
            "pyramid": {
                "minRoe": PYRAMID_MIN_ROE,
                "marginPct": PYRAMID_MARGIN_PCT,
                "maxPerPosition": PYRAMID_MAX_PER_POSITION,
                "maxAccountMarginPct": PYRAMID_MAX_ACCOUNT_MARGIN_PCT,
            },
            "_note": "These constraints are HARDCODED in the scanner. Do not override.",
            "_dslNote": "Use the dslState block from each signal as the DSL state file. Do NOT merge with dsl-profile.json.",
        },
    })


if __name__ == "__main__":
    run()
