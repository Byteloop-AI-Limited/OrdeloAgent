"""Profit check for one order: read-only, from delivery_option.breakdown.
    . Finds the vehicle type that completed the order (delivery_detail), or use --vehicle
    . Prints the revenue split (commission, driver payout, processing fee, profit)
    . Shows every vehicle option so you can see what profit each rider type would have made
  Functions/Classes:
    . main

Usage:
    python .claude/skills/database-operations/scripts/order_profit.py --order ELAS-XSRQ-21
    python .claude/skills/database-operations/scripts/order_profit.py --order ELAS-XSRQ-21 --vehicle car
"""

import argparse

from _bootstrap import execute_with_fallback


def main() -> int:
    parser = argparse.ArgumentParser(description="Profit made on an order (read-only).")
    parser.add_argument("--order", required=True, help="Order number, e.g. ELAS-XSRQ-21")
    parser.add_argument("--vehicle", default=None, help="Vehicle type; default = the one with a rider assigned/completed")
    parser.add_argument("--service", action="store_true", help="Skip the anon client and use the service-role key")
    args = parser.parse_args()

    detail = execute_with_fallback(
        lambda c: c.table("delivery_detail")
        .select("vehicle_type,status,rider_id")
        .eq("order_number", args.order)
        .execute(),
        service=args.service,
    ).data
    options = execute_with_fallback(
        lambda c: c.table("delivery_option")
        .select("vehicle_type,driver_payout,breakdown")
        .eq("order_number", args.order)
        .execute(),
        service=args.service,
    ).data
    if not options:
        print(f"No delivery_option rows for {args.order} (order missing, or RLS hid them: retry with --service).")
        return 1

    vehicle = args.vehicle
    if vehicle is None:
        # The vehicle type that got a rider; fall back to completed status.
        chosen = [d for d in detail if d.get("rider_id")] or [d for d in detail if d.get("status") == "completed"]
        vehicle = chosen[0]["vehicle_type"] if chosen else None
    if vehicle is None:
        print("No rider assigned yet; pass --vehicle. Options:", ", ".join(o["vehicle_type"] for o in options))
        return 1

    status = next((d["status"] for d in detail if d["vehicle_type"] == vehicle), "n/a")
    sel = next((o for o in options if o["vehicle_type"] == vehicle), None)
    if sel is None:
        print(f"No delivery_option for vehicle '{vehicle}'.")
        return 1
    b = sel["breakdown"]

    print(f"\n=== Profit: {args.order} ({vehicle}, status {status}) ===\n")
    rows = [
        ("Final order value (charged)", b["final_order_value"]),
        (f"Commission ({int(b['commission_rate'] * 100)}%)", b["commission"]),
        (f"Service charge ({int(b['service_charge_rate'] * 100)}%)", b["service_charge"]),
        ("Delivery fee", b["delivery_fee"]),
        ("Small order fee", b["small_order_fee"]),
        ("Driver payout", b["driver_payout"]),
        ("Payment processing fee", b["payment_processing_fee"]),
    ]
    for label, val in rows:
        print(f"  {label:<30} £{val:>8.2f}")
    print(f"  {'PROFIT':<30} £{b['profit']:>8.2f}\n")
    print(f"  Distance: {b['distance_miles']} miles")

    print("\nAll vehicle options:")
    for o in sorted(options, key=lambda x: x["breakdown"]["profit"], reverse=True):
        mark = "  <-- used" if o["vehicle_type"] == vehicle else ""
        print(f"  {o['vehicle_type']:<14} payout £{o['driver_payout']:>6.2f}  profit £{o['breakdown']['profit']:>6.2f}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
