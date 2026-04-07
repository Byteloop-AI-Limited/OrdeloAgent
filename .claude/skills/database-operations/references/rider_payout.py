"""
Rider payout report for a given date range.

Usage:
    PYTHONPATH=/home/user/OrdeloAgent /usr/bin/python3.13 \
        .codex/skills/database-operations/references/rider_payout.py \
        --start 2026-03-27

    # or with explicit end (inclusive):
    PYTHONPATH=/home/user/OrdeloAgent /usr/bin/python3.13 \
        .codex/skills/database-operations/references/rider_payout.py \
        --start 2026-03-27 --end 2026-04-02

Start date is always a Friday. If --end is omitted, end date defaults to
the Thursday 6 days later (i.e. the full week up to but excluding the next Friday).

Excludes Lohith (rider_id 447448440754) — internal test rider.
Joins: delivery_dispatch → rider_master → rider_registrations → delivery_option
"""

import argparse
from collections import defaultdict
from datetime import date, timedelta
from config import client_ordelo

EXCLUDE_RIDER_ID = "447448440754"


def fetch_payouts(start_date: str, end_date: str):
    # 1. Completed dispatches in range
    dispatches = (
        client_ordelo.table("delivery_dispatch")
        .select("order_number, rider_id, rider_payout, dtts")
        .eq("status", "completed")
        .neq("rider_id", EXCLUDE_RIDER_ID)
        .gte("dtts", start_date)
        .lte("dtts", end_date)
        .order("dtts", desc=True)
        .execute()
        .data
    )

    if not dispatches:
        print(f"No completed dispatches between {start_date} and {end_date}.")
        return

    rider_ids = list({d["rider_id"] for d in dispatches})
    order_numbers = [d["order_number"] for d in dispatches]

    # 2. Rider master
    riders = {
        r["rider_id"]: r
        for r in client_ordelo.table("rider_master")
        .select("rider_id, rider_name, vehicle_type")
        .in_("rider_id", rider_ids)
        .execute()
        .data
    }

    # 3. Rider registrations — phone stripped of leading digit = rider_id
    reg_rows = (
        client_ordelo.table("rider_registrations")
        .select("phone, bank_account_name, sort_code, bank_account")
        .execute()
        .data
    )
    reg_by_rider = {r["phone"][1:]: r for r in reg_rows}

    # Join
    detailed = []
    for d in dispatches:
        rider = riders.get(d["rider_id"])
        if not rider:
            continue
        reg = reg_by_rider.get(d["rider_id"])
        if not reg:
            continue
        detailed.append({
            "bank_account_name": reg["bank_account_name"],
            "sort_code": reg["sort_code"],
            "bank_account": reg["bank_account"],
            "order_number": d["order_number"],
            "rider_payout": d["rider_payout"],
            "dtts": d["dtts"],
        })

    print(f"=== Detailed Per-Order Payout ({start_date} to {end_date}) ===")
    for row in detailed:
        print(row)
    print(f"\nTotal orders: {len(detailed)}")

    print("\n=== Aggregated Payout Per Rider ===")
    agg = defaultdict(lambda: {"rider_payout": 0.0, "order_count": 0})
    for row in detailed:
        key = (row["bank_account_name"], row["sort_code"], row["bank_account"])
        agg[key]["rider_payout"] += row["rider_payout"]
        agg[key]["order_count"] += 1

    for (name, sort, acct), totals in agg.items():
        print({
            "bank_account_name": name,
            "sort_code": sort,
            "bank_account": acct,
            "rider_payout": round(totals["rider_payout"], 2),
            "order_count": totals["order_count"],
        })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rider payout report")
    parser.add_argument("--start", required=True, help="Start date inclusive, always a Friday (YYYY-MM-DD)")
    parser.add_argument("--end", required=False, default=None,
                        help="End date inclusive (YYYY-MM-DD). Defaults to the Thursday 6 days after start.")
    args = parser.parse_args()

    start = args.start
    end = args.end or (date.fromisoformat(start) + timedelta(days=6)).isoformat()
    fetch_payouts(start, end)
