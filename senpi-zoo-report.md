# Running the Zoo: Multi-Animal Senpi Deployment Report

**From:** Robbie Heeger ([@rheeger](https://github.com/rheeger))
**Date:** March 6, 2026
**Branch:** `deploy/multi-animal` on `rheeger/senpi-skills` (HEAD: `7b76f94`)
**Platform:** OpenClaw on dedicated Ubuntu VM, DSL v5.1, 22 active crons

---

## What We're Running

I've been running three Senpi animals — FOX, TIGER, and WOLF — from a single OpenClaw instance on a dedicated VM. All three share one `senpi-skills` submodule checkout on our `deploy/multi-animal` fork branch. The goal is to experiment with different strategy approaches simultaneously and see what works.

This doc covers the architecture, what we've learned per animal, the bugs we found and fixed (some gnarly ones), and what would make keeping a multi-animal setup easier going forward. I've tried to be exhaustive — I know you'll probably feed this to agents, so there's enough detail for them to work with.

---

## Architecture

### Suite System

We use a `suite-branches.json` config to map suite names to their paths in the submodule:

```json
{
  "defaultSuite": "tiger",
  "submoduleRoot": "skills/senpi-trading/senpi-skills",
  "suites": {
    "tiger": { "branch": "deploy/multi-animal", "suitePath": "tiger-strategy" },
    "fox": { "branch": "deploy/multi-animal", "suitePath": "fox-strategy" },
    "wolf": { "branch": "deploy/multi-animal", "suitePath": "wolf-strategy" }
  }
}
```

An `animals.json` registry maps each animal instance to its wallet and strategy ID:

```json
{
  "defaultAnimal": "tiger-alpha",
  "animals": {
    "tiger-alpha": {
      "suite": "tiger",
      "wallet": "0x9ef07bf9c46628ca8c3b8fc43a194c4f8c2dbf32",
      "strategyId": "ecc453a7-89df-48a4-b550-23dfa7265892",
      "enabled": true
    }
  }
}
```

A `suite-map.py` script resolves suite metadata at deploy time — branch, paths, scripts directory, adapter hooks. Every deploy target uses it.

### Deployment

`make deploy-workspace` is the single command that does everything:

1. Pre-deploy validation (env vars, cron config, model registry)
2. Git pull + submodule sync to pinned commit
3. Deploy cron-jobs.json
4. Restart OpenClaw + rotate sessions
5. Run 8-phase diagnostics suite

If diagnostics fail, the deploy exits non-zero and we know something's wrong before the next cron fires.

### MCP Call Routing & Security

All Senpi MCP calls go through a wrapper script that handles credential injection. The agent process never holds the Senpi API token — credentials are fetched from a secrets manager and injected into the mcporter subprocess environment only for the duration of the call. If an agent session gets compromised or a cron goes haywire, it can't exfiltrate the trading credentials because it never has them.

```
Cron fires
  -> scanner script runs (Python, deterministic)
  -> script calls mcporter via wrapper
  -> wrapper fetches credentials from secrets manager
  -> credentials injected into mcporter subprocess env
  -> mcporter calls Senpi MCP
  -> credentials discarded after call completes
```

### Circuit Breaker

A separate cron runs every 5 minutes, reads `consecutiveErrors` from `jobs.json`, and auto-disables any job that hits 5 consecutive failures. Sends a Discord alert when it trips. This saved us a few times when API connectivity went down — instead of burning tokens on retries, the circuit breaker kills the cron and we get notified.

---

## The Animals

### FOX (v0.2) — Primary, Most Active

FOX is the most mature animal in our zoo. Multi-strategy architecture via `fox-strategies.json`, 8 crons, and — critically — a self-healing health check.

**Crons (8 total):**

| Job                 | Interval | Model        | Purpose                              |
| ------------------- | -------- | ------------ | ------------------------------------ |
| Emerging Movers v5  | 3min     | Sonnet       | SM rank scanner + entry execution    |
| DSL Combined v6     | 3min     | Gemini Flash | Trailing stops for all FOX positions |
| SM Flip Detector v6 | 5min     | Gemini Flash | Close on smart money conviction flip |
| Watchdog v6         | 5min     | Gemini Flash | Liquidity buffer monitoring          |
| Portfolio v6        | 15min    | Gemini Flash | Position summary to Discord          |
| Health Check v6     | 10min    | Gemini Flash | Auto-fix DSL/state issues            |
| Scanner v6          | 15min    | Haiku        | Opportunity scoring + entry routing  |
| Market Regime       | 4h       | Sonnet       | BTC regime classification            |

**What works well:**

- `fox-health-check.py` is the standout. It auto-fixes orphan DSL files, creates missing DSL for positions that exist on-chain, reconciles size/entry/leverage drift, and deactivates stale state. TIGER has nothing like this — and we paid for it (more on that below).
- Tiered margin system (22%/15%/7% by entry count) manages risk well as position count grows.
- Market regime detector refreshes every 4h and gates entries based on BTC conditions.
- Multi-strategy routing — the scanner picks the best-fit strategy by available slots and risk profile.

**Config highlights:**

```json
{
  "strategies": {
    "fox-0bbe3462": {
      "budget": 999.0,
      "slots": 2,
      "maxEntries": 6,
      "marginTiers": [
        { "entries": [1, 2], "marginPct": 0.22, "margin": 219.78 },
        { "entries": [3, 4], "marginPct": 0.15, "margin": 149.85 },
        { "entries": [5, 6], "marginPct": 0.07, "margin": 69.93 }
      ],
      "defaultLeverage": 5,
      "dailyLossLimit": 149.85
    }
  }
}
```

### TIGER (v4.1) — Intensive Scanner Suite

TIGER takes a different approach — 5 specialized scanners looking for different signal patterns, a confluence scoring system, and a goal-based aggression engine. More moving parts, more crons, more surface area for bugs (which we found).

**Crons (12 total):**

| Job                 | Interval | Model        | Purpose                                 |
| ------------------- | -------- | ------------ | --------------------------------------- |
| Prescreener         | 5min     | Gemini Flash | Score ~230 assets, write top 30         |
| Compression Scanner | 5min     | Haiku        | BB squeeze breakout detection           |
| Correlation Scanner | 5min     | Haiku        | BTC/ETH lag detection                   |
| Momentum Scanner    | 5min     | Haiku        | Price + volume momentum                 |
| Reversion Scanner   | 5min     | Haiku        | Mean reversion setups                   |
| Funding Scanner     | 30min    | Haiku        | Funding rate arbitrage                  |
| OI Tracker          | 5min     | Gemini Flash | Open interest data collection           |
| Goal Engine         | 1h       | Sonnet       | Aggression level + target recalc        |
| Risk Guardian       | 5min     | Sonnet       | Daily loss, drawdown, position limits   |
| Exit Checker        | 5min     | Sonnet       | Pattern-specific exit signals           |
| DSL Trailing Stops  | 3min     | Gemini Flash | Shared DSL v5 trailing stops            |
| ROAR Analyst        | 8h       | Sonnet       | Meta-optimizer for execution thresholds |

**5 signal patterns with confluence scoring:**

| Pattern              | Key Logic                                            | DSL Phase 1 Retrace |
| -------------------- | ---------------------------------------------------- | ------------------- |
| COMPRESSION_BREAKOUT | 4h BB squeeze + 1h breakout + OI buildup             | 0.015               |
| BTC_CORRELATION_LAG  | Leader moves, alt lags. Multi-window (1h/4h/12h/24h) | 0.015               |
| MOMENTUM_BREAKOUT    | >1.5% 1h or >2.5% 2h move + volume confirm           | 0.012 (tighter)     |
| MEAN_REVERSION       | 4h RSI extreme + divergence/exhaustion signals       | 0.015               |
| FUNDING_ARB          | Annualized funding >30%, trade opposite crowd        | 0.020 (wider)       |

Each scanner outputs a weighted confluence score. Entry threshold varies by aggression level:

```json
{
  "minConfluenceScore": {
    "CONSERVATIVE": 0.7,
    "NORMAL": 0.4,
    "ELEVATED": 0.4,
    "ABORT": 999
  }
}
```

**Config:**

```json
{
  "budget": 900,
  "target": 1800,
  "deadlineDays": 7,
  "maxSlots": 3,
  "maxLeverage": 10,
  "minLeverage": 5,
  "maxSingleLossPct": 5,
  "maxDailyLossPct": 12,
  "maxDrawdownPct": 20
}
```

**What we learned:** TIGER's scanner diversity is powerful — it catches signals FOX misses (especially correlation lag and mean reversion). But the 12-cron architecture has more coordination surface area, and bugs cascade harder when shared state gets corrupted. More on this in the bugs section.

### WOLF (v6.1.1) — Currently Paused

WOLF is paused while we experiment with FOX and TIGER. 6 crons, Emerging Movers-based signal detection. Shares DSL v5 and the emerging-movers infrastructure with FOX. Strategy code is preserved and can be re-enabled alongside the other animals.

---

## DSL v5.1 (Shared Across All Animals)

The Dynamic Stop Loss engine is the most important shared component. One script (`dsl-v5.py`), used by FOX, TIGER, and WOLF.

**How it works:**

- Strategy-scoped: one cron per strategy, uses `DSL_STATE_DIR` + `DSL_STRATEGY_ID`
- Discovers positions from MCP clearinghouse (not from skill-level state)
- Per-position state files at `{state_dir}/{strategyId}/{ASSET}.json`
- Archive-on-close: renames to `{ASSET}_archived_{reason}_{epoch}.json`
- Syncs stop-loss orders to Hyperliquid via `edit_position`
- Phase 1 (early position): market close on breach, higher retrace tolerance
- Phase 2 (tiered): limit close, tighter retrace, profit lock via tier upgrades

**Per-pattern DSL tuning:**
We tune DSL retrace thresholds per pattern — momentum gets tighter (0.012) because the move should be fast and decisive, funding arb gets wider (0.020) because the trade needs time to converge. This per-pattern tuning lives in `tiger-open-position.py` and gets written into the DSL state file at entry time.

**What works well:**

- The archive-on-close pattern is clean. When clearinghouse shows a position is gone, DSL archives the state file and moves on. No lingering state.
- Strategy-scoped crons mean FOX and TIGER DSL runs never interfere with each other.
- The Hyperliquid SL sync via `edit_position` is a nice safety net — even if the cron stops running, the exchange-level stop loss is already set.

**What doesn't work well:**

- When DSL closes a position, it archives its own state file but has no way to notify the skill-level state (e.g., `tiger-state.json`). This caused our biggest production outage — more below.

---

## Bugs Found and Fixed

This is the bulk of the value in this doc. All of these were real production issues that took TIGER offline for 24+ hours. We've fixed them all on our fork.

### 1. Clearinghouse Response Parsing (Root Cause)

**The bug:** `strategy_get_clearinghouse_state` returns `{data: {main: {assetPositions: [...]}}}` but all TIGER scripts accessed `main` at the top level of the response. Four files had the same bug, each with slightly different (but equally wrong) parsing:

```python
# What every TIGER script did:
ch = get_clearinghouse(wallet)
ch_data = ch.get("data", ch)
margin_summary = ch_data.get("marginSummary", {})  # Never found — it's under ch_data.main
positions = ch_data.get("assetPositions", [])        # Never found — same issue
```

**Impact:**

- `count_on_chain_positions()` always returned 0 — slot check was broken
- `extract_position()` always returned None — entry price was always 0
- Risk guardian was completely blind to all positions
- Goal engine used stale balance (fell back to state file)
- Slot counting always showed 0, so max slots were never enforced

**Fix:** Unwrap the `data` envelope in `get_clearinghouse()` and navigate into `main` for marginSummary/assetPositions in each consumer script.

**Files changed:** `tiger_config.py`, `tiger-open-position.py`, `risk-guardian.py`, `goal-engine.py`

This is the exact "3 copies of the same 75%" problem from the Senpi architecture post. Four files, four copies of response-unwrapping logic, all wrong. A shared `get_clearinghouse()` that returns clean data would have eliminated this entire class of bug.

### 2. entryPrice=0 State Corruption

**The bug:** Caused by #1. Since `extract_position()` never found the position data (wrong nesting), `tiger-open-position.py` fell through to the fallback path:

```python
# Fallback when clearinghouse parsing fails:
entry_price = 0                              # Zero!
size = round(args.margin * args.leverage, 6) # USD notional, not asset units!
```

Every position opened by TIGER had `entryPrice: 0` and `size` as USD notional (e.g., 2400.0 instead of 7142.0 WIF). This corrupted both the DSL state file and `tiger-state.json`.

**Fix:** Retry clearinghouse fetch 3x with 2s delay. If still no fill data, fall back to market price via `market_get_prices` (with correct response parsing — prices are under `data.prices`, not `data`). If both fail, refuse to write state at all rather than writing zeros.

### 3. DSL ZeroDivisionError

**The bug:** When `entryPrice=0` reached DSL v5, it crashed:

```python
margin = entry * size / leverage  # 0 * 2400 / 8 = 0
upnl_pct = upnl / margin * 100   # division by zero
```

DSL crashed with `ZeroDivisionError` every 3 minutes, flooding Discord with error alerts.

**Fix:** Added a zero-entry guard in `process_one_position()` that deactivates corrupt state files gracefully instead of crashing:

```python
if not entry or entry <= 0 or not size or size <= 0:
    state["active"] = False
    state["closeReason"] = "zero_entry_data: state is corrupt, deactivating"
    # write state, return error JSON, don't crash
```

We also clamped `leverage = max(1, state.get("leverage", 1))` to prevent a secondary division-by-zero path.

### 4. Ghost Positions in tiger-state.json

**The bug:** This one kept recurring. When DSL closes a position, it correctly archives its own state file (`XPL_archived_external_1772776618.json`). But nothing updates `tiger-state.json`, which still shows the position as active.

Every scanner checks `tiger-state.json` for slot availability:

```python
active_coins = set(state.get("active_positions", {}).keys())
available_slots = config["max_slots"] - len(active_coins)
```

With 3 ghost positions, `available_slots = 3 - 3 = 0`. TIGER goes completely silent — all scanners report HEARTBEAT_OK with 0 slots, for hours, until someone manually clears the ghosts.

**Fix:** Added `reconcile_positions()` to `tiger_config.py`:

```python
def reconcile_positions(state, config):
    """Remove ghost positions not on-chain."""
    ch = get_clearinghouse(wallet)
    on_chain = {pos coin for pos in clearinghouse if szi != 0}
    ghosts = [k for k in state["active_positions"] if k not in on_chain]
    if ghosts:
        for g in ghosts:
            del state["active_positions"][g]
        save_state(state)
    return state
```

Called by all 7 scanner/monitor scripts before checking slots. Every 5-minute scan cycle now self-heals if positions were closed externally.

This is a structural gap — DSL owns position lifecycle at the execution layer but has no way to notify the skill layer. The `reconcile_positions()` approach works (poll clearinghouse every scan) but it's a workaround for a missing coordination point between the script layer and the skill layer.

### 5. DSL State File Discovery

**The bug:** Our diagnostics system looked for `dsl-*.json` files, but TIGER uses `{ASSET}.json` naming (e.g., `WIF.json`, `ETH.json`). Also needed to exclude `_archived` files that the DSL creates on close.

**Fix:** Updated `find_dsl_state_files()` to find all `*.json` in the strategy state directory, excluding known non-DSL files (`tiger-state.json`, `trade-log.json`) and `_archived` files.

---

## Diagnostics System

We built an 8-phase E2E diagnostics suite that runs on every deploy. It catches most of the issues above before they hit production.

**Phases:**

| Phase | Name                 | What It Checks                                                  |
| ----- | -------------------- | --------------------------------------------------------------- |
| 1     | Environment          | Python venv, gate adapter, mcporter symlink, runtime wrapper    |
| 2     | Cron Config          | Script paths exist, MCPORTER_CMD in payloads, model assignments |
| 3     | Tool Connectivity    | market_list_instruments, market_get_prices, clearinghouse       |
| 4     | Source Audit         | No bare mcporter calls, no direct Hyperliquid API calls         |
| 5     | Script Execution     | Dry-run each scanner, verify JSON output structure              |
| 6     | Close Path           | Full close_position chain (gate -> auth -> Senpi API)           |
| 7     | DSL Risk Scenarios   | Trailing stop behavior: crash, bleed, recovery, tier upgrades   |
| 8     | State Reconciliation | **New — catches the exact failures from this session**          |

**Phase 8 (added today) catches:**

- Active DSL files with `entryPrice=0`
- Size values in USD notional instead of asset units
- Ghost DSL files (active state but no position on-chain)
- Ghost positions in `tiger-state.json`
- DSL resilience to zero-entry corrupt state (must deactivate, not crash)

Phase 8 runs in quick mode (file reads + one clearinghouse call), so it's included in every deploy without adding significant time.

Sample output when things are broken:

```
--- 8-State-Reconciliation ---

  [FAIL [CRITICAL]] state_clearinghouse_sync
    DSL ↔ clearinghouse mismatch: ghost DSL (no position on-chain): AAVE, ARB, ETH, XPL
    FIX: Remove ghost DSL files or run health check to auto-reconcile

  [FAIL [CRITICAL]] state_tiger_ghost_positions
    tiger-state.json lists positions not on-chain: AAVE, ARB, ETH, XPL
    FIX: Reset tiger-state.json active_positions to match clearinghouse

============================================================
  UNSAFE TO TRADE -- 2 critical failure(s)
============================================================
```

And when everything's clean:

```
--- 8-State-Reconciliation ---

  [PASS] state_entry_price_nonzero — All 1 active DSL files have valid entryPrice
  [PASS] state_size_units — All active DSL sizes appear to be in asset units
  [PASS] state_clearinghouse_sync — 1 positions on-chain, 1 active DSL files
  [PASS] state_tiger_ghost_positions — tiger-state.json matches clearinghouse (1 positions)
  [PASS] state_dsl_zero_entry_resilience — DSL with entryPrice=0: deactivated gracefully

============================================================
  SAFE TO TRADE -- 61/61 passed
============================================================
```

---

## The Scripts/Plugins/Skills Vision — We're Living It

Read the Senpi architecture post about letting each layer do what it's best at. Our experience is direct evidence for that thesis.

**Our bugs are the "3 copies of the same 75%" problem:**

The clearinghouse parsing bug existed in `tiger-open-position.py`, `risk-guardian.py`, `goal-engine.py`, and `tiger-exit.py` — four copies of response-unwrapping logic, each slightly different, all wrong. A plugin with one `get_clearinghouse()` that returns clean data eliminates this entire class of bug.

The ghost position problem exists because DSL (shared script) and `tiger-state.json` (skill-level state) have no coordination point. A `senpi-trading` plugin handling position lifecycle would own both sides.

`reconcile_positions()` — our fix that cross-checks clearinghouse on every scan — is exactly the kind of thing that should be a plugin operation, not copy-pasted into 7 scanner scripts.

FOX health check auto-heals DSL state drift. TIGER has no equivalent. A shared health-check plugin would give every skill self-healing for free.

**What we built that maps to plugin candidates:**

| Our Code                                           | Plugin It Should Be                                       |
| -------------------------------------------------- | --------------------------------------------------------- |
| `reconcile_positions()` in `tiger_config.py`       | `senpi-trading` plugin: position lifecycle sync           |
| `_unwrap_ch()` response handling                   | `senpi-trading` plugin: standardized MCP response parsing |
| Phase 8 diagnostics                                | Standard post-deploy validation for any skill             |
| `fox-health-check.py` auto-healing                 | Shared health-check plugin, configurable per skill        |
| Per-pattern DSL tuning in `tiger-open-position.py` | DSL plugin with pattern-aware configuration               |

**We're ready for the 4-step migration:**

- **Step 1 (DSL as plugin):** We already use DSL v5 as a shared script across FOX and TIGER. Moving it to a plugin would eliminate the last coordination gap — when DSL closes a position, the plugin could fire a callback that updates skill-level state. This single change would have prevented our biggest production outage.
- **Step 2 (Skills consume DSL plugin):** Our `deploy/multi-animal` branch already has all three skills pointing at the same DSL v5 script. We're ready to migrate.
- **Step 3 (senpi-trading plugin):** Our `tiger_config.py` shared helpers (`get_clearinghouse`, `create_position`, `reconcile_positions`, `get_prices`) are a prototype of what this plugin should contain. Happy to contribute our battle-tested versions.
- **Step 4 (Skill Dev Guide):** We'd love to see response envelope conventions documented. The `{data: {main: ...}}` vs `{data: {prices: ...}}` inconsistency is the kind of thing a plugin hides, but until plugins exist, skills need clear schemas.

---

## What Would Help Us

Things that would make keeping our zoo running smoother while the plugin architecture matures:

**MCP response schema documentation.** Until plugins abstract this away, skill authors need to know the response shape for each tool. We burned a full day on a parsing bug that a schema doc would have prevented. Even a simple table — tool name, response structure, where the actual data lives — would be huge.

**DSL close lifecycle hook.** When DSL closes a position, the skill layer has no way to know. Even before the full plugin, a simple mechanism — env var for a post-close script, a callback path in the DSL state file, an event written to a shared location — would let skills react to DSL-initiated closes. This is the #1 source of state desync for us.

**Generalized health check.** FOX's `fox-health-check.py` is excellent. Extracting it into a shared script (or future plugin) that any skill can configure would close the self-healing gap. We'd contribute to building this.

**Multi-suite deployment guidance.** We run FOX + TIGER + WOLF from one submodule on `deploy/multi-animal`. This works but diverges from upstream. Would love guidance on whether multi-suite should be one branch (our approach) or something the submodule structure supports natively.

**Response envelope consistency.** `market_get_prices` returns `{data: {prices: {WIF: "0.21"}}}` while `strategy_get_clearinghouse_state` returns `{data: {main: {...}}}`. Standardizing the unwrapping — or at minimum documenting it per-tool — would reduce integration friction for everyone building skills.

---

## Model Selection Findings

We tier our model assignments by how much judgment the cron actually requires:

| Tier              | Model        | Used For                                                        | Rationale                                                                  |
| ----------------- | ------------ | --------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Data relay        | Gemini Flash | OI Tracker, DSL, Prescreener                                    | Parse JSON, output JSON. No judgment. Cheapest option.                     |
| Scanner execution | Haiku        | Compression, Correlation, Momentum, Reversion, Funding          | Parse scanner output, maybe call `tiger-open-position.py`. Fast and cheap. |
| Risk decisions    | Sonnet       | Risk Guardian, Exit Checker, Goal Engine, ROAR, Emerging Movers | Portfolio-level judgment calls. Worth the cost.                            |

This maps directly to the Scripts/Plugins/Skills split: scripts produce facts (any model works), plugins execute operations (model doesn't matter), AI makes decisions (best model required).

The data relay tier is a good candidate for elimination entirely once plugins exist — a DSL plugin doesn't need an LLM at all.

---

## Offering

We're happy to contribute upstream:

- `reconcile_positions()` — battle-tested clearinghouse state sync
- Phase 8 diagnostics — state reconciliation checks that catch ghost positions, zero entries, size-unit mismatches
- Response envelope unwrapping patterns we've validated against production MCP responses
- Testing and feedback on the plugin migration as it rolls out

Our fork is at [rheeger/senpi-skills](https://github.com/rheeger/senpi-skills) on the `deploy/multi-animal` branch. All fixes are in commits `da3ae46` through `7b76f94`.

R
