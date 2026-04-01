# 🔥 PHOENIX v1.0.1 — Contribution Velocity Scanner

Part of the [Senpi Trading Skills](https://github.com/Senpi-ai/senpi-skills).

## The Signal

Phoenix finds assets where SM profit contribution is accelerating but price hasn't moved yet. This **divergence** — SM knows something the market doesn't — is the pre-move signal.

Best trade: HYPE SHORT at 54x divergence ratio. Held 2.6 days. +50.8% ROE. +$101 profit.

## How It Works

One API call (`leaderboard_get_markets`). Zero state files. The scanner computes `contribution_pct_change_4h / token_price_change_pct_4h`. When that ratio exceeds 5x — SM contribution is accelerating 5x faster than price is moving — that's the signal.

## Key Settings

| Setting | Value |
|---|---|
| Leverage | 10x |
| Max positions | 3 |
| Max entries/day | 6 |
| Min divergence ratio | 5x |
| Min score | 7 |
| DSL timeouts | 120m hard / 60m weak peak / 45m dead weight |

## License

MIT — Copyright 2026 Senpi (https://senpi.ai)
