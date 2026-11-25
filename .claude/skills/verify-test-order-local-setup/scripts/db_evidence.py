#!/usr/bin/env python3
"""Read-only evidence for local test orders. Run from a prepared OrdeloAgent shell (venv, PYTHONPATH, envLoad).

  db_evidence.py preflight [REF]        shared URLs, webhooks, STRK policy, pickup defaults, on-shift overwatch riders
  db_evidence.py watch SECONDS [REF]    print each summary / dispatch state change as it happens
  db_evidence.py order ORDER_NUMBER     events, alerts, dispatches and payment events of one order

The connection is opened read-only; the only network call is Telegram getWebhookInfo in preflight.
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from config.pg_setting import pg_settings


def connect():
    return psycopg.connect(
        pg_settings.db_uri, autocommit=True, prepare_threshold=None, row_factory=dict_row,
        connect_timeout=15, options="-c default_transaction_read_only=on",
    )


def show(c, title, sql, *args):
    print("##", title)
    for r in c.execute(sql, args).fetchall():
        print("  ", " | ".join(f"{k}={v}" for k, v in r.items()))


async def webhooks():
    from config.tgram_setting import rest_admin_bot, rider_bot

    print("## telegram webhooks")
    for name, bot in (("rest-admin", rest_admin_bot), ("rider", rider_bot)):
        try:
            info = await asyncio.wait_for(bot.get_webhook_info(), 20)
            print("  ", name, info.url, "pending", info.pending_update_count, info.last_error_message or "")
        except Exception as exc:
            print("  ", name, "unavailable:", type(exc).__name__)
        finally:
            await bot.session.close()


def preflight(ref):
    with connect() as c:
        show(c, "shared URLs", "select config_key,config_value from ordelo_config where config_key in ('ORDELO_APP_URL','RESTAURANT_MENU_APP_URL','ENABLE_SIMULATE_PAYMENT')")
        show(c, "silence policy", "select r.rest_ref,r.city,r.auto_accept,p.* from restaurant_master r cross join lateral restaurant_confirmation_policy(r.rest_ref::text) p where r.rest_ref=%s", ref)
        show(c, "pickup defaults", "select 'delivery' kind,* from restaurant_default_pickup_minutes(%s,'delivery') union all select 'takeaway',* from restaurant_default_pickup_minutes(%s,'takeaway')", ref, ref)
        show(c, "stored overrides (restore these)", "select config_key,quote_nullable(config_value) v from ordelo_config where config_key = any(%s)", [f"{ref}_DEFAULT_DELIVERY_PICKUP_TIME", f"{ref}_DEFAULT_COLLECTION_PICKUP_TIME"])
        show(c, "overwatch riders on shift in this town", "select rider_name,town,vehicle_type from rider_master where is_in_shift and town=(select city from restaurant_master where rest_ref=%s) and rider_id::text = any(string_to_array((select config_value from ordelo_config where config_key='overwatch_list'),','))", ref)
        show(c, "open orders", "select order_number,status,restaurant_confirmation_status from delivery_summary where rest_ref=%s and status in ('restaurant_unconfirmed','unassigned','assigned','inflight') and dtts>now()-interval '1 day'", ref)
    asyncio.run(webhooks())


def watch(seconds, ref):
    last, end = {}, time.time() + seconds
    started = datetime.now(timezone.utc)
    with connect() as c:
        while time.time() < end:
            rows = []
            for table in ("delivery_summary", "takeaway_summary"):
                rows += [(table, r["order_number"], r) for r in c.execute(f"select order_number,restaurant_confirmation_status,status,pickup_time,dtts from {table} where rest_ref=%s and dtts>%s::timestamptz-interval '40 minutes'", (ref, started)).fetchall()]
            rows += [("dispatch", r["dispatch_id"], r) for r in c.execute("select d.dispatch_id,d.order_number,d.rider_id,d.status from delivery_dispatch d join delivery_summary s using(order_number) where s.rest_ref=%s and s.dtts>%s::timestamptz-interval '40 minutes'", (ref, started)).fetchall()]
            for kind, key, r in rows:
                value = " ".join(str(v) for v in r.values())
                if last.get((kind, key)) != value:
                    last[(kind, key)] = value
                    print(datetime.now(timezone.utc).strftime("%H:%M:%SZ"), kind, value, flush=True)
            time.sleep(1.5)


def order(number):
    short = number.split("-", 1)[1]
    with connect() as c:
        show(c, "order", "select order_number,payment_mode,payment_status,total_price,final_order_value,origin_channel from food_order where order_number=%s", number)
        for table in ("delivery_summary", "takeaway_summary"):
            show(c, table, f"select status,restaurant_confirmation_status,dtts,pickup_time,pickup_time-dtts as after_order,ready_at from {table} where order_number=%s", number)
        show(c, "dispatches", "select dispatch_id,rider_id,status from delivery_dispatch where order_number=%s order by 1", number)
        show(c, "customer events", "select event_key,occurred_at from order_customer_event where order_number=%s order by id", number)
        show(c, "telegram alerts", "select offset_secs,status from t_order_alerts where order_number=%s order by id", number)
        show(c, "payment events", "select kind,received_at from payment_event where order_id=%s order by received_at", short)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "preflight":
        preflight((rest or ["STRK"])[0])
    elif cmd == "watch":
        watch(float(rest[0]), (rest[1:] or ["STRK"])[0])
    elif cmd == "order":
        order(rest[0])
    else:
        sys.exit(__doc__)
    sys.stdout.flush()
    os._exit(0)  # imported config opens pools that would otherwise keep the process alive
