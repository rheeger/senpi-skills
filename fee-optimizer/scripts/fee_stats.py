#!/usr/bin/env python3
"""
Compute fee-related stats (FDR, total fees, maker fill %, gross vs net PnL) for a wallet or strategy.
Intended for use by an agent with Senpi MCP: pass wallet/strategy and optional date range;
agent should call strategy_get_clearinghouse_state / trade history and pass data in or run in MCP context.
When run without MCP, prints stub output structure per references/fee-computations.md.
Usage: python3 fee_stats.py [--wallet ADDR] [--strategy-id ID] [--from DATE] [--to DATE]
Output: JSON to stdout.
"""
import argparse
import json
import sys
from datetime import datetime, timezone


def compute_fee_stats(
    total_fees: float | None = None,
    account_start_value: float | None = None,
    maker_fills: int | None = None,
    total_fills: int | None = None,
    gross_pnl: float | None = None,
    rotation_count: int | None = None,
    notional_per_rotation: float | None = None,
) -> dict:
    """Compute metrics from raw inputs. All args optional; omitted metrics are null."""
    out = {
        "totalFees": total_fees,
        "fdrPct": None,
        "makerFillPct": None,
        "grossPnl": gross_pnl,
        "netPnl": None,
        "rotationCount": rotation_count,
        "rotationCostUsd": None,
    }
    if total_fees is not None and account_start_value is not None and account_start_value > 0:
        out["fdrPct"] = round((total_fees / account_start_value) * 100, 4)
    if maker_fills is not None and total_fills is not None and total_fills > 0:
        out["makerFillPct"] = round((maker_fills / total_fills) * 100, 2)
    if gross_pnl is not None and total_fees is not None:
        out["netPnl"] = round(gross_pnl - total_fees, 2)
    if rotation_count is not None and notional_per_rotation is not None:
        # ~6 bps hybrid round-trip per rotation as rough default
        out["rotationCostUsd"] = round(rotation_count * notional_per_rotation * (6 / 10000), 2)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Fee stats for wallet/strategy. Use with MCP for live data.")
    parser.add_argument("--wallet", metavar="ADDR", help="Strategy wallet address")
    parser.add_argument("--strategy-id", metavar="ID", help="Strategy ID")
    parser.add_argument("--from", dest="from_date", metavar="DATE", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", metavar="DATE", help="End date (YYYY-MM-DD)")
    parser.add_argument("--total-fees", type=float, help="Total fees (for testing or piped data)")
    parser.add_argument("--account-start", type=float, help="Account start value for FDR")
    parser.add_argument("--gross-pnl", type=float, help="Gross PnL")
    args = parser.parse_args()

    # Without MCP we have no clearinghouse; allow minimal override for testing / stub
    total_fees = getattr(args, "total_fees", None)
    account_start = getattr(args, "account_start", None)
    gross_pnl = getattr(args, "gross_pnl", None)

    stats = compute_fee_stats(
        total_fees=total_fees,
        account_start_value=account_start,
        gross_pnl=gross_pnl,
    )
    if not any((args.wallet, args.strategy_id, total_fees, account_start, gross_pnl)):
        stats["_note"] = "Run by agent with Senpi MCP to pass clearinghouse/trade data; or use --total-fees, --account-start, --gross-pnl for stub."
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
