# Senpi Skills — Agent Instructions

## MCP Routing: Gate Wrapper Required

**All Senpi MCP calls MUST go through the gate wrapper.** Never use bare `mcporter call senpi.*` — it bypasses auth injection and will fail with `SENPI_AUTH_TOKEN not set`.

### How It Works

The gate wrapper (`runtime/bin/mcporter-senpi-wrapper.sh`) routes `senpi.*` calls through `mcporter-gate/handler.py`, which fetches the auth token from the passkey gate vault and injects it as an ephemeral env var. The token never touches the environment directly.

### For Scripts (Python)

Every config module (`fox_config.py`, `wolf_config.py`, `tiger_config.py`, `lion_config.py`) and standalone scripts (`dsl-v5.py`, `emerging-movers.py`) include a `_resolve_mcporter()` function that auto-discovers the gate wrapper. Scripts do not need `MCPORTER_CMD` set — they find the wrapper relative to their own file location.

The resolution priority is:

1. `MCPORTER_CMD` env var (if explicitly set)
2. Auto-discovered wrapper at `../../../runtime/bin/mcporter-senpi-wrapper.sh` (relative to script)
3. Bare `mcporter` fallback (only if wrapper not found)

**Do not bypass this.** Never call `subprocess.run(["mcporter", ...])` directly in scripts. Always use `mcporter_call()` from the appropriate config module, or use `MCPORTER_BIN` / `_MCPORTER_BIN` in standalone scripts.

### For Cron Jobs (Agent Mandates)

When constructing cron commands that run Senpi scripts, you MUST include the `MCPORTER_CMD` env var pointing to the wrapper. This is a defense-in-depth measure — scripts auto-discover the wrapper, but explicit env vars ensure correctness even if the relative path resolution fails.

**Required env var prefix for ALL senpi cron commands:**

```
MCPORTER_CMD=/home/arnold/.openclaw/workspace/skills/senpi-trading/runtime/bin/mcporter-senpi-wrapper.sh
```

**Full cron command pattern:**

```
MCPORTER_CMD=/home/arnold/.openclaw/workspace/skills/senpi-trading/runtime/bin/mcporter-senpi-wrapper.sh \
{SKILL}_WORKSPACE=/home/arnold/.openclaw/workspace \
NPM_CONFIG_CACHE=/tmp/npm-cache \
PYTHONUNBUFFERED=1 \
python3 /home/arnold/.openclaw/workspace/skills/senpi-trading/senpi-skills/{skill}/scripts/{script}.py
```

Replace `{SKILL}_WORKSPACE` with the appropriate env var for the skill:

- TIGER: `TIGER_WORKSPACE` + `TIGER_CONFIG`
- FOX: `FOX_WORKSPACE` + `OPENCLAW_WORKSPACE`
- WOLF: `WOLF_WORKSPACE` + `OPENCLAW_WORKSPACE`

### What NOT To Do

- **Never** call `mcporter call senpi.*` directly in agent tool calls without the gate wrapper
- **Never** edit cron job messages to remove the `MCPORTER_CMD` env var prefix
- **Never** create new cron jobs for senpi scripts without the full env var block
- **Never** use bare `python3 script.py` without the env var prefix in cron mandates
- **Never** hardcode `"mcporter"` in new Python scripts — always use the config module's `mcporter_call()`

### Troubleshooting

| Error                              | Cause                                                    | Fix                                                                                                             |
| ---------------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `SENPI_AUTH_TOKEN not set`         | Script called bare `mcporter` instead of gate wrapper    | Ensure `MCPORTER_CMD` points to wrapper, or verify auto-discovery finds `runtime/bin/mcporter-senpi-wrapper.sh` |
| `Expecting value: line 1 column 1` | API returned empty response (auth failure or rate limit) | Check gate service is running, check passkey-gate vault has valid Senpi token                                   |
| `mcporter: command not found`      | Wrapper not found and bare mcporter not in PATH          | Set `MCPORTER_CMD` explicitly in cron env vars                                                                  |
| `Read-only file system`            | Script trying to write outside allowed paths             | Set workspace env vars (`TIGER_WORKSPACE`, `FOX_WORKSPACE`, etc.) to `/home/arnold/.openclaw/workspace`         |
