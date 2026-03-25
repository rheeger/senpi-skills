# 🍋 LEMON v1.0 — The Degen Fader

Part of the [Senpi Trading Skills](https://github.com/Senpi-ai/senpi-skills).

## Thesis

Find the worst traders on Hyperliquid (DEGEN activity + CHOPPY consistency).
Wait until they're over-leveraged (20x+) and bleeding (-10%+ ROE). Take the
opposite side. Ride the liquidation cascade.

## How It Works

1. Scanner finds DEGEN/CHOPPY traders via `discovery_get_top_traders`
2. Checks their live positions via `discovery_get_trader_state`
3. Scores vulnerability: leverage × bleeding × cluster × SM × funding
4. Score 6+ → enter opposite direction at 5x leverage
5. DSL manages all exits (trailing stops, floors, timeouts)

## Key Settings

| Setting | Value |
|---|---|
| Leverage | 5x (conservative) |
| Target leverage | >= 20x (over-leveraged degens) |
| Target ROE | <= -10% (actively bleeding) |
| Min score | 6 |
| Max positions | 2 |
| Max entries/day | 4 |
| Cooldown | 3 hours per asset |
| DSL floor | -15% ROE |
| DSL timeout | 60 min |

## License

MIT — Copyright 2026 Senpi (https://senpi.ai)
