# 🦂 SCORPION — DEPRECATED

**Status:** Deprecated as of March 13, 2026
**Replaced by:** MANTIS v2.0
**Leaderboard record:** -24.2% ROI, 406 trades

## Why Deprecated

SCORPION and MANTIS v1.0 shared the same broken data source: `discovery_get_top_traders` → read current open positions. This surfaced legacy positions (months-old shorts/longs) as fresh signals. SCORPION's loose filters (2 whales, 10-minute aging) amplified the problem — it took 406 trades in a market where "fewer trades wins" is the proven pattern (Fox: 82 trades, +32%).

## What Replaced It

MANTIS v2.0 uses `leaderboard_get_momentum_events` (real-time threshold crossings) instead of stale position reads. It replaces both SCORPION and MANTIS v1.0 with a single, properly-sourced skill.

## Files (archived, do not deploy)

The original SCORPION v1.1 files are preserved in the repo for historical reference but should not be deployed.

| File | Status |
|---|---|
| `scripts/scorpion-scanner.py` | Archived — uses deprecated data source |
| `scripts/scorpion_config.py` | Archived |
| `config/scorpion-config.json` | Archived |
