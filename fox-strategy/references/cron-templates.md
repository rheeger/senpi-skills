# Cron Templates — Fox v0.2

> Per Senpi Skill Guide §7: all crons use isolated/agentTurn with `message` key.
> Replace placeholders: `{WORKSPACE}`, `{SCRIPTS}`, `{TELEGRAM}`, `{MID_MODEL}`, `{BUDGET_MODEL}`.

## Placeholder Reference

| Placeholder | Scope | Example |
|------------|-------|---------|
| `{WORKSPACE}` | Workspace root | `/data/workspace` |
| `{SCRIPTS}` | Scripts directory | `/data/workspace/scripts` |
| `{TELEGRAM}` | Telegram target | `telegram:<chat_id>` |
| `{MID_MODEL}` | Mid-tier model ID | `anthropic/claude-sonnet-4-5` |
| `{BUDGET_MODEL}` | Budget-tier model ID | `anthropic/claude-haiku-4-5` |

## 1. Emerging Movers — Mid / Isolated

```json
{
  "name": "FOX — Emerging Movers (3min)",
  "schedule": { "kind": "cron", "expr": "*/3 * * * *", "tz": "UTC" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "model": "{MID_MODEL}",
    "message": "FOX Scanner: Run `PYTHONUNBUFFERED=1 python3 {SCRIPTS}/fox-emerging-movers.py`, parse JSON.\nSLOT GUARD: If `anySlotsAvailable` is false AND `hasFirstJump` is false -> HEARTBEAT_OK.\nAct ONLY on `topPicks` array. Process topPicks[0] first, then topPicks[1], etc.\nEnter via: `python3 {SCRIPTS}/fox-open-position.py --strategy {strategyKey} --asset {qualifiedAsset} --signal-index {signalIndex}`\nThe `qualifiedAsset` field includes `xyz:` prefix for XYZ equities. Use it directly.\nROTATION: Only rotate coins in `strategySlots[strategy].rotationEligibleCoins`. If `hasRotationCandidate` is false -> skip rotation. Add `--close-asset {coin}` to rotate.\nFor each successful entry, send each message in `notifications` from open-position.py output to {TELEGRAM}.\nIf no actionable signals -> HEARTBEAT_OK."
  }
}
```

## 2. DSL v5 — Mid / Isolated

```json
{
  "name": "FOX — DSL Combined (3min)",
  "schedule": { "kind": "cron", "expr": "*/3 * * * *", "tz": "UTC" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "model": "{MID_MODEL}",
    "message": "FOX DSL: Run `PYTHONUNBUFFERED=1 python3 {SCRIPTS}/fox-dsl-wrapper.py`, parse JSON.\nFor each item in `action_required`: close that position (coin + strategyKey wallet), alert {TELEGRAM}.\nSend each message in `notifications` to {TELEGRAM}.\nIf both empty -> HEARTBEAT_OK."
  }
}
```

## 3. SM Flip Detector — Budget / Isolated

```json
{
  "name": "FOX — SM Flip Detector (5min)",
  "schedule": { "kind": "cron", "expr": "*/5 * * * *", "tz": "UTC" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "model": "{BUDGET_MODEL}",
    "message": "FOX SM: Run `python3 {SCRIPTS}/fox-sm-flip-check.py`, parse JSON.\nFor each item in `action_required`: close that position (coin + strategyKey wallet), alert {TELEGRAM}.\nSend each message in `notifications` to {TELEGRAM}.\nIf both empty -> HEARTBEAT_OK."
  }
}
```

## 4. Watchdog — Budget / Isolated

```json
{
  "name": "FOX — Watchdog (5min)",
  "schedule": { "kind": "cron", "expr": "*/5 * * * *", "tz": "UTC" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "model": "{BUDGET_MODEL}",
    "message": "FOX Watchdog: Run `PYTHONUNBUFFERED=1 timeout 45 python3 {SCRIPTS}/fox-monitor.py`, parse JSON.\nFor each item in `action_required`: close the specified position (coin + strategyKey), alert {TELEGRAM}.\nSend each message in `notifications` to {TELEGRAM}.\nIf both empty -> HEARTBEAT_OK."
  }
}
```

## 5. Portfolio Update — Mid / Isolated

```json
{
  "name": "FOX — Portfolio (15min)",
  "schedule": { "kind": "cron", "expr": "*/15 * * * *", "tz": "UTC" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "model": "{MID_MODEL}",
    "message": "FOX Portfolio: Read `{WORKSPACE}/fox-strategies.json`. For each enabled strategy, call `strategy_get_clearinghouse_state` with the strategy wallet.\nFormat a code-block table with: per-strategy name, account value, positions (asset, direction, ROE%, PnL, DSL tier), slot usage, and global totals.\nSend to {TELEGRAM}."
  }
}
```

## 6. Opportunity Scanner — Mid / Isolated

```json
{
  "name": "FOX — Opportunity Scanner (15min)",
  "schedule": { "kind": "cron", "expr": "*/15 * * * *", "tz": "UTC" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "model": "{MID_MODEL}",
    "message": "FOX Scanner: Run `PYTHONUNBUFFERED=1 timeout 180 python3 {SCRIPTS}/fox-opportunity-scan-v6.py`, parse JSON.\nSLOT GUARD: If `anySlotsAvailable` is false -> HEARTBEAT_OK.\nFor each opportunity in `topPicks`: enter via `python3 {SCRIPTS}/fox-open-position.py --strategy {strategyKey} --asset {qualifiedAsset} --signal-index {signalIndex}`.\nSend each message in `notifications` to {TELEGRAM}. Else HEARTBEAT_OK."
  }
}
```

## 7. Market Regime Refresh — Mid / Isolated

```json
{
  "name": "FOX — Market Regime (4h)",
  "schedule": { "kind": "cron", "expr": "0 */4 * * *", "tz": "UTC" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "model": "{MID_MODEL}",
    "message": "FOX Regime: Run `PYTHONUNBUFFERED=1 python3 {SCRIPTS}/fox-market-regime.py`, parse JSON.\nSave the full output to `{WORKSPACE}/market-regime-last.json`.\nHEARTBEAT_OK after saving."
  }
}
```

## 8. Health Check — Mid / Isolated

```json
{
  "name": "FOX — Health Check (10min)",
  "schedule": { "kind": "cron", "expr": "*/10 * * * *", "tz": "UTC" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "model": "{MID_MODEL}",
    "message": "FOX Health: Run `PYTHONUNBUFFERED=1 python3 {SCRIPTS}/fox-health-check.py`, parse JSON.\nSend each message in `notifications` to {TELEGRAM}.\nIf `notifications` is empty -> HEARTBEAT_OK."
  }
}
```

## Summary Table

| # | Cron | Interval | Session | Payload Kind | Model |
|---|------|----------|---------|-------------|-------|
| 1 | Emerging Movers | */3 * * * * | isolated | agentTurn | Mid |
| 2 | DSL Combined | */3 * * * * | isolated | agentTurn | Mid |
| 3 | SM Flip | */5 * * * * | isolated | agentTurn | Budget |
| 4 | Watchdog | */5 * * * * | isolated | agentTurn | Budget |
| 5 | Portfolio | */15 * * * * | isolated | agentTurn | Mid |
| 6 | Opp Scanner | */15 * * * * | isolated | agentTurn | Mid |
| 7 | Market Regime | 0 */4 * * * | isolated | agentTurn | Mid |
| 8 | Health Check | */10 * * * * | isolated | agentTurn | Mid |
