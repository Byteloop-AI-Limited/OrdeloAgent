"""Thin CLI wrapper around watomation.routers.sys_admin_auth_session.fetch_payouts.
    . Delegates payout aggregation logic to the FastAPI router module (single source of truth)
    . Prints the detailed + aggregated payout sections to stdout
    . Start date is always a Friday; --end defaults to the Thursday 6 days later
    . Excludes Lohith (rider_id 447448440754) — enforced inside fetch_payouts
  Functions/Classes:
    . main

Usage:
    PYTHONPATH=$(git rev-parse --show-toplevel) python3 \
        .claude/skills/database-operations/references/rider_payout.py \
        --start 2026-03-27

    # or with explicit end (inclusive):
    PYTHONPATH=$(git rev-parse --show-toplevel) python3 \
        .claude/skills/database-operations/references/rider_payout.py \
        --start 2026-03-27 --end 2026-04-02
"""

import argparse
from datetime import date, timedelta

from watomation.routers.sys_admin_auth_session import fetch_payouts


def main() -> None:
    parser = argparse.ArgumentParser(description="Rider payout report")
    parser.add_argument(
        "--start",
        required=True,
        help="Start date inclusive, always a Friday (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        required=False,
        default=None,
        help="End date inclusive (YYYY-MM-DD). Defaults to the Thursday 6 days after start.",
    )
    args = parser.parse_args()

    start = args.start
    end = args.end or (date.fromisoformat(start) + timedelta(days=6)).isoformat()

    report = fetch_payouts(start, end)

    if report["total_orders"] == 0:
        print(f"No completed dispatches between {report['start']} and {report['end']}.")
        return

    print(f"=== Detailed Per-Order Payout ({report['start']} to {report['end']}) ===")
    for row in report["detailed"]:
        print(row)
    print(f"\nTotal orders: {report['total_orders']}")

    print("\n=== Aggregated Payout Per Rider ===")
    for row in report["aggregated"]:
        print(row)


if __name__ == "__main__":
    main()
