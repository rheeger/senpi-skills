# 🦂 SCORPION — Whale Wallet Tracker

The poisonous tail. Tracks top whale wallets from the leaderboard, monitors their position changes, mirrors entries with a 10-minute delay filter (filters out noise/hedges). When a tracked whale exits, SCORPION exits immediately — the sting.

## Architecture

| Script | Freq | Purpose |
|--------|------|---------|
| `scorpion-scanner.py` | 5 min | Discover whales, track positions, detect consensus, mirror entries |
| DSL v5 (shared) | 3 min | Trailing stops |

## Edge

Top whales have information edges (flow, OTC, insider). Following their positions with a delay filter captures the edge while avoiding noise. The instant exit on whale exit (the sting) protects against whale reversals.

## Setup

1. Set `SCORPION_WALLET` and `SCORPION_STRATEGY_ID` env vars (or fill `scorpion-config.json`)
2. Create cron: scanner every 5 min + DSL v5 every 3 min
