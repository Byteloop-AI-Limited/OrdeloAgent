"""
R3: web-origin isolation and customer tracking safeguards.
R1b customer events, subscriptions and at-most-once restaurant delivery.

publish atomically records an event and its outbox rows in the existing R1
tables. Dispatch claims a row before I/O: restaurant retries are deliberately
zero, including after ambiguous timeouts or process death. WebPageAdapter is
a no-op until R3; web origins can never use RestaurantAppWebhookAdapter.
notify_address handles the two pre-order address hooks, which cannot reference
food_order yet. sweep_pending recovers unattempted rows, not failed deliveries.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from config.feature_flags import (
    CUSTOMER_NOTIFIER_ENABLED,
    CUSTOMER_NOTIFIER_REST_REFS,
    config_csv,
    flag_enabled,
)
from config.params import get_restaurant_webhook_url_async
from config.pg_setting import pg_settings, client_ordelo
from utils_common.order_management.customer_keys import is_web_customer_key


@dataclass(frozen=True)
class CustomerOrderEvent:
    event_type: str
    event_key: str
    webhook_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    path_suffix: str = ""
    follow_redirects: bool = False
    is_estimate: bool = False

    def data(self) -> dict:
        return {
            "webhook_type": self.webhook_type,
            "payload": self.payload,
            # JSONB reorders object keys. Keep the original HTTP bytes as text
            # so dispatch after persistence preserves the legacy request body.
            "body_json": httpx.Request(
                "POST", "https://notification.invalid", json=self.payload
            ).content.decode("utf-8"),
            "path_suffix": self.path_suffix,
            "follow_redirects": self.follow_redirects,
        }


async def enabled_for(rest_ref: str) -> bool:
    """Missing flag = off; a nonempty allowlist limits the pilot to those refs."""
    if not await flag_enabled(CUSTOMER_NOTIFIER_ENABLED):
        return False
    try:
        refs = await config_csv(CUSTOMER_NOTIFIER_REST_REFS, fail_on_error=True)
    except Exception:
        logger.warning("customer notifier: rollout lookup failed; disabled")
        return False
    return not refs or rest_ref.upper() in refs


class RestaurantAppWebhookAdapter:
    """Exactly one POST using the legacy URL, JSON and redirect policy."""

    async def send(self, rest_ref: str, data: dict) -> None:
        base = await get_restaurant_webhook_url_async(rest_ref, data["webhook_type"])
        async with httpx.AsyncClient(
            follow_redirects=data.get("follow_redirects", False)
        ) as client:
            url = base + data.get("path_suffix", "")
            if "body_json" in data:
                response = await client.post(
                    url,
                    content=data["body_json"].encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
            else:
                response = await client.post(url, json=data["payload"])
            response.raise_for_status()


class WebPageAdapter:
    """The future page reads the recorded event; no HTTP or WhatsApp is sent."""

    async def send(self, rest_ref: str, data: dict) -> None:
        return None


async def notify_address(rest_ref: str, recipient: str, payload: dict) -> None:
    """Pre-order routing; no event FK exists yet, so do not invent an order."""
    if is_web_customer_key(recipient):
        logger.info("customer notifier: web address hook skipped rest_ref={}", rest_ref)
        return
    await RestaurantAppWebhookAdapter().send(
        rest_ref,
        {
            "webhook_type": "order-address-update",
            "path_suffix": f"/{recipient}",
            "payload": payload,
        },
    )


async def _ensure_origin_subscription(cur, order: dict) -> None:
    web = order.get("origin_channel", "whatsapp") == "web" or is_web_customer_key(
        order["recipient"]
    )
    await cur.execute(
        """
        INSERT INTO order_notification_subscription
            (order_number, channel, destination, source)
        VALUES (%s, %s, %s, 'order_origin') ON CONFLICT DO NOTHING
    """,
        (
            order["order_number"],
            "web_page" if web else "whatsapp_restaurant",
            None if web else order["recipient"],
        ),
    )


async def create_origin_subscription(order_number: str) -> None:
    """Best effort after order creation; publish repairs older/missing subscriptions."""
    try:
        pool = await pg_settings.get_pool()
        async with (
            pool.connection() as conn,
            conn.transaction(),
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "SELECT order_number, recipient, origin_channel FROM food_order WHERE order_number=%s",
                (order_number,),
            )
            order = await cur.fetchone()
            if order:
                await _ensure_origin_subscription(cur, order)
    except Exception as exc:
        logger.error(
            "customer notifier: subscription failed order={} error_type={}",
            order_number,
            type(exc).__name__,
        )


async def _record(order_number: str, event: CustomerOrderEvent) -> list[int]:
    pool = await pg_settings.get_pool()
    async with (
        pool.connection() as conn,
        conn.transaction(),
        conn.cursor(row_factory=dict_row) as cur,
    ):
        # All workers serialize this order's event/subscription writes.
        await cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (order_number,)
        )
        await cur.execute(
            "SELECT order_number, recipient, origin_channel FROM food_order WHERE order_number=%s",
            (order_number,),
        )
        order = await cur.fetchone()
        if not order:
            raise ValueError("Unknown notification order")
        await cur.execute(
            """
            INSERT INTO order_customer_event (order_number,event_key,event_type,is_estimate,data)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT (order_number,event_key) DO NOTHING
        """,
            (
                order_number,
                event.event_key,
                event.event_type,
                event.is_estimate,
                Jsonb(event.data()),
            ),
        )
        await cur.execute(
            "SELECT id FROM order_customer_event WHERE order_number=%s AND event_key=%s",
            (order_number, event.event_key),
        )
        event_id = (await cur.fetchone())["id"]
        await cur.execute(
            "SELECT id FROM order_notification_subscription WHERE order_number=%s AND active",
            (order_number,),
        )
        if not await cur.fetchall():
            await _ensure_origin_subscription(cur, order)
        await cur.execute(
            """
            INSERT INTO notification_outbox(event_id,subscription_id)
            SELECT %s,id FROM order_notification_subscription WHERE order_number=%s AND active
            ON CONFLICT(event_id,subscription_id) DO NOTHING
        """,
            (event_id, order_number),
        )
        await cur.execute(
            "SELECT id FROM notification_outbox WHERE event_id=%s AND status='pending' AND attempts=0",
            (event_id,),
        )
        return [row["id"] for row in await cur.fetchall()]


async def _claim(outbox_id: int) -> dict | None:
    pool = await pg_settings.get_pool()
    async with (
        pool.connection() as conn,
        conn.transaction(),
        conn.cursor(row_factory=dict_row) as cur,
    ):
        await cur.execute(
            """
            UPDATE notification_outbox SET attempts=1,updated_at=now()
            WHERE id=%s AND status='pending' AND attempts=0 RETURNING id
        """,
            (outbox_id,),
        )
        if not await cur.fetchone():
            return None
        await cur.execute(
            """
            SELECT e.order_number,e.data,s.channel,s.destination,s.detail_level,s.active,
                   f.origin_channel,f.recipient
            FROM notification_outbox o JOIN order_customer_event e ON e.id=o.event_id
            JOIN order_notification_subscription s ON s.id=o.subscription_id
            JOIN food_order f ON f.order_number=e.order_number WHERE o.id=%s
        """,
            (outbox_id,),
        )
        return await cur.fetchone()


async def _finish(outbox_id: int, status: str, error: str | None = None) -> None:
    pool = await pg_settings.get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "UPDATE notification_outbox SET status=%s,last_error=%s,updated_at=now() WHERE id=%s",
            (status, error, outbox_id),
        )


async def dispatch(outbox_id: int) -> None:
    row = await _claim(outbox_id)
    if not row:
        return
    status, error = "skipped", None
    rest_ref = row["order_number"].split("-")[0]
    try:
        if not row["active"]:
            pass
        elif row["channel"] == "web_page":
            await WebPageAdapter().send(rest_ref, row["data"])
        elif row["channel"] == "whatsapp_restaurant":
            # Destination/detail mismatches must not leak the legacy full payload.
            if (
                row["origin_channel"] == "web"
                or is_web_customer_key(row["recipient"])
                or row["destination"] != row["recipient"]
                or row["detail_level"] != "full"
            ):
                error = (
                    "Restaurant channel incompatible with order origin or subscription"
                )
            else:
                await RestaurantAppWebhookAdapter().send(rest_ref, row["data"])
                status = "sent"
        else:
            error = "Channel adapter unavailable until R4"
    except Exception as exc:
        status, error = "failed", type(exc).__name__
    await _finish(outbox_id, status, error)
    logger.info(
        "customer notifier: order={} channel={} outcome={} attempts=1",
        row["order_number"],
        row["channel"],
        status,
    )


async def publish(order_number: str, event: CustomerOrderEvent) -> None:
    """Record and dispatch without making fulfilment depend on a customer app."""
    try:
        for outbox_id in await _record(order_number, event):
            await dispatch(outbox_id)
    except Exception as exc:
        # Persist the intent via REST when the direct pool is unavailable.
        # No legacy HTTP fallback: that risks a leak or a duplicate delivery.
        try:
            await asyncio.to_thread(lambda: client_ordelo.table("order_customer_event").upsert({
                "order_number": order_number, "event_key": event.event_key,
                "event_type": event.event_type, "is_estimate": event.is_estimate, "data": event.data(),
            }, on_conflict="order_number,event_key", ignore_duplicates=True).execute())
        except Exception:
            logger.error("customer notifier: both persistence paths failed order={} event={}; manual reconciliation required", order_number, event.event_key)
        # Never bypass routing on failure: that would leak web orders or double-send.
        logger.error(
            "customer notifier: publish failed order={} event={} error_type={}",
            order_number,
            event.event_key,
            type(exc).__name__,
        )


async def sweep_pending() -> int:
    """Recover committed but unattempted events; never retry an HTTP attempt."""
    notifier_on = await flag_enabled(CUSTOMER_NOTIFIER_ENABLED)
    web_on = await flag_enabled('WEB_LATE_PAYMENT_GUARD_ENABLED')
    if not notifier_on and not web_on:
        return 0
    pool = await pg_settings.get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""
            INSERT INTO order_notification_subscription(order_number,channel,destination,source)
            SELECT DISTINCT f.order_number,CASE WHEN f.origin_channel='web' THEN 'web_page' ELSE 'whatsapp_restaurant' END,
                CASE WHEN f.origin_channel='web' THEN NULL ELSE f.recipient END,'order_origin'
            FROM food_order f JOIN order_customer_event e ON e.order_number=f.order_number
            WHERE NOT EXISTS(SELECT 1 FROM order_notification_subscription s WHERE s.order_number=f.order_number AND s.active)
            ON CONFLICT DO NOTHING
        """)
        await cur.execute("""
            INSERT INTO notification_outbox(event_id,subscription_id)
            SELECT e.id,s.id FROM order_customer_event e JOIN order_notification_subscription s ON s.order_number=e.order_number AND s.active
            ON CONFLICT(event_id,subscription_id) DO NOTHING
        """)
        await cur.execute("""
            UPDATE notification_outbox SET status='failed',last_error='Interrupted attempt; no retry',updated_at=now()
            WHERE status='pending' AND attempts>0 AND updated_at<now()-interval '5 minutes'
        """)
        await cur.execute("""
            SELECT o.id,e.order_number,f.origin_channel FROM notification_outbox o
            JOIN order_customer_event e ON e.id=o.event_id
            JOIN food_order f ON f.order_number=e.order_number
            WHERE o.status='pending' AND o.attempts=0 AND o.next_attempt_at<=now()
            ORDER BY o.id LIMIT 100
        """)
        rows = await cur.fetchall()
    count = 0
    for row in rows:
        if (web_on and row.get("origin_channel") == "web") or await enabled_for(row["order_number"].split("-")[0]):
            await dispatch(row["id"])
            count += 1
    return count


async def run_sweeper() -> None:
    """Application-owned 60-second sweep; no new SQL or cron registration."""
    while True:
        try:
            await sweep_pending()
            from utils_common.web_ordering.lifecycle import sweep
            await sweep()
            from utils_common.web_ordering.monitoring import sweep as audit_prices
            await audit_prices()
        except Exception as exc:
            logger.error(
                "customer notifier: sweep failed error_type={}", type(exc).__name__
            )
        await asyncio.sleep(60)
