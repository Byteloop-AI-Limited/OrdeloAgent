"""Web-only late-payment release and abandoned checkout maintenance.

The late-authorisation decision and release intent commit before replying to
Stripe; the sweep recovers crashes. This never initializes a rejected order.
Retries here apply to payment cancellation, not restaurant-app notifications.

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . food_order (table, restaurant-agents): reads (SQL)
  . order_customer_event (table, ordelo_datamodels/notifications/order_customer_event.sql): reads (SQL)
  . payment_event (table, ordelo_datamodels/payment/payment_event.sql): writes (SQL)
  . thread (table, restaurant-agents): writes (SQL)
  . web_payment_release (table, ordelo_datamodels/ordering/web_payment_release.sql): reads (SQL), writes (SQL)
  . web_rate_limit (table, ordelo_datamodels/ordering/web_rate_limit.sql): reads (SQL)
  . web_session_meta (table, ordelo_datamodels/ordering/web_session_meta.sql): reads (SQL)
(end of database objects)
"""

import asyncio
from datetime import timedelta
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from config.pg_setting import pg_settings
from loguru import logger
from utils_common.notify import customer_notifier
from utils_common.notify.customer_notifier import CustomerOrderEvent
from .common import one, query, utcnow
from .availability import available
from .common import WebError


async def queue_release(order_number, reason):
    """Insert a durable web payment-cancellation intent if none exists.

    Repeated calls keep the first reason and existing retry/completion state.
    Callers must supply a web order; this helper does not inspect its origin.
    """
    await query(
        """INSERT INTO web_payment_release(order_number,reason) VALUES (%s,%s)
        ON CONFLICT DO NOTHING""",
        (order_number, reason),
    )


async def reject_late(evt):
    """Reject a pending web authorisation after 35 minutes or restaurant closure.

    Return None for normal/non-web events, late_rejected after an atomic event,
    release-intent and WEB-thread update, or late_rejected_duplicate for a replay.
    Recheck payment state under a row lock; transient availability errors propagate
    rather than cancelling a valid order. No fulfilment is initialized here.
    """
    if evt is None:
        return None
    order = await one("SELECT * FROM food_order WHERE order_id=%s", (evt.order_id,))
    if not order or order.get("origin_channel") != "web":
        return None
    if await one(
        "SELECT 1 FROM web_payment_release WHERE order_number=%s",
        (order["order_number"],),
    ):
        return "late_rejected_duplicate"
    late = utcnow() > order["order_dtts"] + timedelta(minutes=35)
    if not late:
        try:
            await available(
                order["order_number"].split("-")[0],
                "delivery" if order["action"] == "delivery" else "collection",
                new_order=False,
            )
        except WebError as exc:
            # A transient DB/pricing/config outage must not be treated as closed.
            if exc.body["error"] != "restaurant_closed":
                raise
            late = True
    if not late:
        return None
    pool = await pg_settings.get_pool()
    async with (
        pool.connection() as conn,
        conn.transaction(),
        conn.cursor(row_factory=dict_row) as cur,
    ):
        await cur.execute("SET LOCAL search_path = public")
        await cur.execute(
            "SELECT payment_status FROM food_order WHERE order_id=%s FOR UPDATE",
            (evt.order_id,),
        )
        if (await cur.fetchone())["payment_status"] != "requires_payment":
            return None
        await cur.execute(
            """INSERT INTO payment_event(provider_event_id,order_id,kind,payment_intent_id,amount_pence,payload)
            VALUES (%s,%s,'cancel_requested',%s,%s,%s) ON CONFLICT(provider_event_id) DO NOTHING RETURNING id""",
            (
                evt.provider_event_id,
                evt.order_id,
                evt.payment_intent_id,
                evt.amount_pence,
                Jsonb({"reason": "web_late_payment"}),
            ),
        )
        if not await cur.fetchone():
            return "late_rejected_duplicate"
        await cur.execute(
            "INSERT INTO web_payment_release(order_number,reason) VALUES (%s,'late_payment') ON CONFLICT DO NOTHING",
            (order["order_number"],),
        )
        await cur.execute(
            "UPDATE thread SET is_active=false WHERE thread_id=%s AND agent='WEB'",
            (order["thread_id"],),
        )
    return "late_rejected"


async def sweep():
    """Expire WEB threads, prune rate counters and claim up to ten release jobs.

    Claim due jobs with SKIP LOCKED and a one-minute next-attempt lease, then
    perform cancellation I/O outside the transaction. Interrupted claims become
    due again. Does not delete orders, grants or session metadata.
    """
    await query("""UPDATE thread SET is_active=false WHERE agent='WEB' AND is_active AND thread_id IN
        (SELECT thread_id FROM web_session_meta WHERE expires_at<now())""")
    await query("DELETE FROM web_rate_limit WHERE window_start<now()-interval '2 days'")
    # Claim before I/O; an interrupted attempt becomes eligible again after 1m.
    jobs = await query("""UPDATE web_payment_release SET attempts=attempts+1,next_attempt_at=now()+interval '1 minute',updated_at=now()
        WHERE order_number IN (SELECT order_number FROM web_payment_release WHERE completed_at IS NULL AND next_attempt_at<=now()
        ORDER BY next_attempt_at LIMIT 10 FOR UPDATE SKIP LOCKED) RETURNING order_number,attempts""")
    for job in jobs:
        await release(job["order_number"], job["attempts"])


async def release(order_number, attempts=1):
    """Attempt cancellation for a queued web order and publish release evidence.

    Existing release evidence completes the job without provider I/O. Otherwise
    try the shared cancel helper up to four times (delays 0, 2, 5, 15 seconds).
    A non-None result marks completion and publishes payment_released; failure
    reschedules for five minutes and alerts on sweep attempts one and three.
    This cancellation path is not a post-capture refund implementation.
    """
    from watomation.routers.delivery_hooks import cancel_payment, notify_overwatch

    recorded = await one(
        """SELECT 1 FROM order_customer_event WHERE order_number=%s
        AND (event_type='payment_released' OR data->'payload'->>'payment_cancelled'='true') LIMIT 1""",
        (order_number,),
    )
    if recorded:
        await query(
            "UPDATE web_payment_release SET completed_at=now(),updated_at=now() WHERE order_number=%s",
            (order_number,),
        )
        return
    result = None
    for delay in (0, 2, 5, 15):
        if delay:
            await asyncio.sleep(delay)
        result = await cancel_payment(order_number)
        if result is not None:
            break
    if result is not None:
        await query(
            "UPDATE web_payment_release SET completed_at=now(),updated_at=now() WHERE order_number=%s",
            (order_number,),
        )
        await customer_notifier.publish(
            order_number,
            CustomerOrderEvent(
                "payment_released",
                "payment_released",
                "web-payment-release",
                {"payment_cancelled": True},
            ),
        )
    else:
        await query(
            "UPDATE web_payment_release SET next_attempt_at=now()+interval '5 minutes' WHERE order_number=%s",
            (order_number,),
        )
        logger.error("web late-payment release pending order={}", order_number)
        if attempts in (1, 3):
            await notify_overwatch(
                f"{order_number}: late web payment release needs reconciliation; no fulfilment started."
            )
