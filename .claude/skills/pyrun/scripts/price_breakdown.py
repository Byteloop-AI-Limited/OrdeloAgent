"""
Price breakdown for a given order number and vehicle type.

Usage:
    PYTHONPATH=$REPO_ROOT /usr/bin/python3.13 \
        .claude/skills/pyrun/scripts/price_breakdown.py \
        --order ELAS-UYWS-20 --vehicle car
"""
import argparse
from config import client_ordelo


def price_breakdown(order_number: str, vehicle_type: str):
    fo = client_ordelo.table("food_order").select("*").eq("order_number", order_number).execute().data
    dd = client_ordelo.table("delivery_detail").select("*").eq("order_number", order_number).eq("vehicle_type", vehicle_type).execute().data
    do = client_ordelo.table("delivery_option").select("*").eq("order_number", order_number).eq("vehicle_type", vehicle_type).execute().data
    all_do = client_ordelo.table("delivery_option").select("vehicle_type, driver_payout, breakdown").eq("order_number", order_number).execute().data

    if not fo:
        print(f"Order {order_number} not found.")
        return
    if not do:
        print(f"No delivery_option found for {order_number} / {vehicle_type}.")
        return

    f = fo[0]
    b = do[0]["breakdown"]
    detail = dd[0] if dd else {}

    print(f"\n=== Price Breakdown: {order_number} ({vehicle_type}) ===\n")

    print("Order Value")
    print(f"  Food total (customer price)       £{f['total_price']:.2f}")
    print(f"  Service charge (7%)               £{b['service_charge']:.2f}")
    print(f"  Delivery fee                       £{b['delivery_fee']:.2f}")
    print(f"  Small order fee                    £{b['small_order_fee']:.2f}")
    print(f"  Final order value (charged)        £{b['final_order_value']:.2f}")

    print("\nRevenue Split")
    print(f"  Restaurant cost                    £{f['rest_cost']:.2f}")
    print(f"  Byteloop commission ({int(b['commission_rate']*100)}%)          £{b['commission']:.2f}")
    print(f"  Driver payout                      £{b['driver_payout']:.2f}")
    print(f"  Payment processing fee             £{b['payment_processing_fee']:.2f}")
    print(f"  Byteloop profit                    £{b['profit']:.2f}")

    print(f"\nCustomer fees                        £{b['total_customer_fee']:.2f}  (delivery £{b['delivery_fee']:.2f} + service charge £{b['service_charge']:.2f})")
    print(f"Distance                             {b['distance_miles']} miles")

    if detail:
        print(f"Status                               {detail.get('status', 'n/a')}")

    if all_do:
        print("\nVehicle comparison for this order:")
        print(f"  {'Vehicle':<16} {'Driver payout':>14} {'Byteloop profit':>16}")
        print(f"  {'-'*16} {'-'*14} {'-'*16}")
        for opt in sorted(all_do, key=lambda x: x["breakdown"]["driver_payout"]):
            marker = " <-- assigned" if opt["vehicle_type"] == vehicle_type else ""
            print(f"  {opt['vehicle_type']:<16} £{opt['driver_payout']:>12.2f}   £{opt['breakdown']['profit']:>13.2f}{marker}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Price breakdown for an order")
    parser.add_argument("--order", required=True, help="Order number e.g. ELAS-UYWS-20")
    parser.add_argument("--vehicle", required=True, help="Vehicle type e.g. car, scooter, electric_bike")
    args = parser.parse_args()
    price_breakdown(args.order, args.vehicle)
