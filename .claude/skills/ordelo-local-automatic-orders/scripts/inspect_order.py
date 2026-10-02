#!/usr/bin/env python3
"""Read one Ordelo order and, optionally, its recorded Stripe TEST intent(s).

Run from a prepared OrdeloAgent shell. No database/provider writes occur.
Personal recipient/destination values are masked; notifier payloads are omitted.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("order_number", help="Full food_order.order_number")
    parser.add_argument("--stripe-secret", help="Authorized AWS secret name for the restaurant's Stripe TEST key")
    parser.add_argument("--stripe-key-field", default="stripetestkey")
    parser.add_argument("--output", type=Path, help="New private JSON snapshot; existing files are not overwritten")
    return parser.parse_args()


def mask_destination(value):
    if not value or (value.startswith("W") and len(value) == 12):
        return value
    return "***" + value[-4:]


def inspect_database(order_number):
    from config.pg_setting import client_ordelo as db

    result = {"checked_at_utc": datetime.now(timezone.utc).isoformat()}
    order = db.table("food_order").select(
        "order_number,order_id,recipient,thread_id,origin_channel,storefront,payment_mode,payment_status"
    ).eq("order_number", order_number).execute().data
    if len(order) != 1:
        raise ValueError(f"Expected one food_order for {order_number}; found {len(order)}")
    short_id = order[0]["order_id"]
    order[0]["recipient"] = mask_destination(order[0]["recipient"])
    result["food_order"] = order
    queries = [
        ("delivery_summary", "order_number,status,dtts,redispatch_dtts,restaurant_confirmation_status,pickup_time", "order_number", order_number),
        ("delivery_detail", "order_number,vehicle_type,status", "order_number", order_number),
        ("delivery_dispatch", "dispatch_id,order_number,status,status_update_dtts", "order_number", order_number),
        ("payment_event", "id,kind,provider_event_id,payment_intent_id,amount_pence,received_at", "order_id", short_id),
        ("payment_details", "order_number,payment_id", "order_number", short_id),
        ("order_notification_subscription", "id,order_number,channel,destination,active,detail_level,source", "order_number", order_number),
    ]
    for table, columns, key, value in queries:
        result[table] = db.table(table).select(columns).eq(key, value).execute().data
    for sub in result["order_notification_subscription"]:
        sub["destination"] = mask_destination(sub.get("destination"))
    events = db.table("order_customer_event").select(
        "id,order_number,event_key,event_type,occurred_at,is_estimate,data"
    ).eq("order_number", order_number).order("id").execute().data
    for event in events:
        data = event.pop("data") or {}
        event["payment_cancelled"] = data.get("payload", {}).get("payment_cancelled")
    result["order_customer_event"] = events
    ids = [event["id"] for event in events]
    result["notification_outbox"] = db.table("notification_outbox").select(
        "id,event_id,subscription_id,status,attempts,last_error,next_attempt_at,updated_at"
    ).in_("event_id", ids).order("id").execute().data if ids else []
    return result


def inspect_stripe(result, secret_name, key_field):
    import httpx
    from aws_setting import get_agent_env

    key = get_agent_env(secret_name)[key_field]
    if not isinstance(key, str) or not key.startswith("sk_test_"):
        raise ValueError("Stripe inspection requires an sk_test_ key; refusing live key")
    intents = {
        row.get("payment_id") for row in result["payment_details"]
    } | {
        row.get("payment_intent_id") for row in result["payment_event"]
    }
    intents.discard(None)
    result["stripe_test_intents"] = []
    fields = ["id", "status", "livemode", "amount", "currency", "amount_received",
              "amount_capturable", "capture_method", "canceled_at", "cancellation_reason"]
    with httpx.Client(headers={"Authorization": "Bearer " + key}, timeout=20) as client:
        for intent in sorted(intents):
            if not intent.startswith("pi_"):
                raise ValueError("Recorded payment ID is not a Stripe PaymentIntent")
            response = client.get("https://api.stripe.com/v1/payment_intents/" + intent)
            response.raise_for_status()
            payment = response.json()
            if payment.get("livemode") is not False:
                raise ValueError("Stripe returned a live-mode PaymentIntent")
            result["stripe_test_intents"].append({field: payment.get(field) for field in fields})


def main():
    args = parse_args()
    try:
        result = inspect_database(args.order_number)
        if args.stripe_secret:
            inspect_stripe(result, args.stripe_secret, args.stripe_key_field)
        payload = json.dumps(result, indent=2, default=str) + "\n"
        if args.output:
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(payload)
        print(payload, end="")
        return 0
    except Exception as error:
        # Provider error bodies, URLs and authorization headers can contain private
        # data. Print the type only; investigate through the normal scoped tools.
        print(f"Order inspection failed ({type(error).__name__}); no writes performed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
