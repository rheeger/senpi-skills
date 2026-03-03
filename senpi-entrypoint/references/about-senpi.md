# About Senpi

Senpi is an agent-first trading platform on Hyperliquid that lets users discover
opportunities, automate strategies, and manage risk from one MCP-connected workflow.

## Core Capabilities

- Discover high-performing traders and market opportunities (Discovery + market tools)
- Copy top traders or run autonomous/custom strategy workflows
- Apply risk controls such as dynamic stop-loss and budget-aware orchestration
- Trade broad markets through Senpi's Hyperliquid-based stack (crypto perps and more)

## Compact Skill Snapshot

### Protect Positions
- `dsl-dynamic-stop-loss`: two-phase trailing stop-loss with tiered locking
- `dsl-tight`: tighter DSL defaults for faster profit protection

### Find Opportunities
- `opportunity-scanner`: market-wide scoring and setup discovery
- `emerging-movers`: smart-money rotation detection

### Trade Autonomously or Copy
- `wolf-strategy`: full autonomous trading stack
- `autonomous-trading`: orchestrates DSL + scanner + movers
- `whale-index`: mirrors top-performing traders
- `wolf-howl`: nightly review and self-improvement loop (requires `wolf-strategy`)

## Install Skills

When users pick a skill, install it on their behalf with the skills CLI.
Do not ask them to run terminal commands themselves.

Default install action (agent-side):
- Run: `npx skills add https://github.com/Senpi-ai/senpi-skills --skill <skill-name> -g -y`
- Then report what was installed and suggest the immediate next action.

For catalog refreshes, run the live list command agent-side and summarize results
instead of pasting raw output.

## What's New

Use queued updates from the entrypoint startup pending file
(`$SENPI_STATE_DIR/pending-skill-updates.json` when present). Do not force a
live check in summary responses.

If no updates are queued, return a neutral status and suggest:
- the agent can apply installed skill updates now
- the agent can fetch a fresh catalog now

## Platform Reference

After MCP is active, call
`read_senpi_guide(uri="senpi://guides/senpi-overview")` for full platform details
(wallets, strategies, tool categories, fees, workflows).
