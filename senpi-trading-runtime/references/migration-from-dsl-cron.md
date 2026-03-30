# Migration Guide: Python DSL Cron → Plugin Runtime

Migrate from the old `dsl-v5.py` cron-based DSL to the plugin-based DSL exit engine.

---

## Who needs this

Skills previously using two crons (scanner + DSL) now use one cron (scanner) + the plugin runtime. If your agent has a `dsl-v5.py` cron running, follow this guide.

---

## Before you start

**Check for open positions**: `openclaw senpi dsl positions`
- Open positions are protected by the old DSL cron
- The migration installs the plugin runtime FIRST, then removes the old cron — no gap in protection
- The `position_tracker` picks up existing positions automatically

---

## Step 1: Get runtime.yaml

Check if `runtime.yaml` exists in your skill directory.

**If it exists** — proceed to Step 2.

**If it doesn't exist**:

1. Check GitHub for the latest: `https://github.com/Senpi-ai/senpi-skills/tree/main/{skill}/runtime.yaml`
2. If not on GitHub, use the template: copy [runtime-template.yaml](runtime-template.yaml) to your skill directory as `runtime.yaml`

**After copying, you MUST update the `dsl_preset` values** to match your skill's original Python DSL config. The template has placeholder values — read your scanner `.py` and map:

| Python (scanner .py) | YAML (runtime.yaml) |
|---|---|
| `retraceThreshold: 0.03` | `retrace_threshold: 3` (multiply by 100) |
| `consecutiveBreachesRequired: 3` | `consecutive_breaches_required: 3` |
| `absoluteFloorRoe: -18` | `max_loss_pct: 18` (positive) |
| `hardTimeoutMin: 25` | `hard_timeout.interval_in_minutes: 25` |
| `weakPeakCutMin: 12` | `weak_peak_cut.interval_in_minutes: 12` |
| `deadWeightCutMin: 8` | `dead_weight_cut.interval_in_minutes: 8` |
| `DSL_TIERS [{triggerPct: 7, lockHwPct: 40}]` | `phase2.tiers [{trigger_pct: 7, lock_hw_pct: 40}]` |

Also update `name:` and `description:` to match your skill.

---

## Step 2: Delete bootstrap marker

```bash
rm config/bootstrap-complete.json
```

Forces the agent to re-bootstrap with the new instructions.

---

## Step 3: Agent re-bootstraps

On next session, the agent reads the updated SKILL.md and runs:

1. Read senpi-trading-runtime skill
2. Set wallet: `sed -i 's/${WALLET_ADDRESS}/<ACTUAL_ADDRESS>/' runtime.yaml`
3. Set telegram: `sed -i 's/${TELEGRAM_CHAT_ID}/<CHAT_ID>/' runtime.yaml`
4. Install: `openclaw senpi runtime create --path runtime.yaml`
5. Verify: `openclaw senpi runtime list`
6. Remove old DSL cron: `openclaw crons list` → `openclaw crons delete <id>` (any cron with `dsl-v5.py`)
7. Verify scanner cron still running

---

## Step 4: Verify

```bash
openclaw senpi runtime list          # runtime installed
openclaw senpi dsl positions         # positions tracked
openclaw crons list                  # only scanner cron, no DSL cron
```

---

## What changed

| Before | After |
|---|---|
| 2 crons (scanner + `dsl-v5.py`) | 1 cron (scanner) + plugin runtime |
| DSL cron polls every 3 min | Plugin monitors every 30s |
| Agent writes DSL state files | `position_tracker` auto-detects on-chain |
| DSL config in Python / JSON | DSL config in `runtime.yaml` |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| runtime.yaml missing | GitHub → migrated skill on machine → [template](runtime-template.yaml). Update DSL values from scanner .py |
| Runtime not listed after install | Check `${WALLET_ADDRESS}` was replaced before installing |
| Old DSL cron still running | `openclaw crons list` → `openclaw crons delete <id>` |
| Positions not in `dsl positions` | Wait 10s (position_tracker poll interval). Verify wallet matches. |
| Rollback needed | Reinstall previous skill version — old SKILL.md recreates DSL cron |
