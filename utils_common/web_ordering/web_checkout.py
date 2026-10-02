"""R3 web sessions and durable idempotent checkout using existing order/payment contracts.

Order + request + address snapshot commit atomically before external payment I/O.
A transaction advisory lock serializes payment-URL retries across processes.
Client unit prices/discounts remain the explicitly accepted D8 risk.
"""

import asyncio
import hashlib
import json
from decimal import Decimal
from datetime import timedelta
from pydantic import BaseModel, Field, ConfigDict, field_validator
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from config.pg_setting import pg_settings
from config.feature_flags import flag_enabled
from utils_common.order_management.customer_keys import new_web_customer_key
from utils_common.order_management.order_reference import new_order_reference
from utils_common.order_management.food_order_pymodel import FoodOrder
from utils_common.payment_ms.payment import (
    generate_payment_intent_url,
    generate_takeaway_manual_payment_url,
)
from utils_common.payment_ms.payment_mode import is_test_payment_allowed
from . import availability, order_access
from .common import MAX_ORDER_LINES, RESTAURANTS, WebError, one, query, utcnow, iso


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    sku: str = Field(min_length=1, max_length=150)
    product_name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(ge=1, le=99, strict=True)
    price: Decimal = Field(ge=0, le=1000, decimal_places=2)
    modifications: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("modifications")
    @classmethod
    def modifications_bounded(cls, values):
        if any(len(value) > 200 for value in values):
            raise ValueError("Modification too long")
        return values


class OrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    thread_id: str = Field(min_length=1, max_length=150)
    cust_id: str = Field(min_length=1, max_length=30)
    rest_ref: str = Field(min_length=4, max_length=4)
    order_items: list[Item] = Field(min_length=1, max_length=MAX_ORDER_LINES)
    notes: str | None = Field(default=None, max_length=500)
    test_payment: bool = False
    client_estimate: dict[str, float | None] = Field(default_factory=dict)

    @field_validator("client_estimate")
    @classmethod
    def finite_estimate(cls, values):
        import math

        if any(
            value is not None and (not math.isfinite(value) or abs(value) > 100000)
            for value in values.values()
        ):
            raise ValueError("Invalid estimate")
        return values


async def start(rest_ref, mode, town_slug, visitor_id, district=None):
    await availability.available(rest_ref, mode)
    if not await flag_enabled("WEB_LATE_PAYMENT_GUARD_ENABLED"):
        raise WebError("ordering_unavailable", 503)
    if town_slug != RESTAURANTS[rest_ref]["town"]:
        raise WebError("unknown_town")
    thread = await one("SELECT * FROM public.create_thread(%s,%s)", ("WEB", None))
    cust_id = new_web_customer_key()
    expiry = utcnow() + timedelta(hours=2)
    await query(
        """INSERT INTO web_session_meta(thread_id,visitor_id,cust_id,rest_ref,mode,town_slug,postcode_district,expires_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            thread["thread_id"],
            visitor_id,
            cust_id,
            rest_ref,
            mode,
            town_slug,
            district,
            expiry,
        ),
    )
    return {
        "thread_id": thread["thread_id"],
        "cust_id": cust_id,
        "expires_at": expiry.isoformat(),
    }


async def session(thread_id, cust_id):
    row = await one(
        "SELECT * FROM web_session_meta WHERE thread_id=%s AND cust_id=%s AND expires_at>now()",
        (thread_id, cust_id),
    )
    if not row:
        raise WebError("no_checkout_session", 409)
    return row


async def address(thread_id, cust_id, value):
    await session(thread_id, cust_id)
    allowed = {
        "flat": 40,
        "building": 60,
        "house_number": 20,
        "street": 80,
        "town": 60,
        "postcode": 10,
        "instructions": 200,
    }
    if any(
        key not in allowed
        or not isinstance(text, (str, type(None)))
        or (text is not None and len(text) > allowed[key])
        for key, text in value.items()
    ):
        raise WebError("invalid_address")
    value = {key: text.strip() for key, text in value.items() if isinstance(text, str)}
    import re

    postcode = value.get("postcode", "").upper().replace(" ", "")
    if not re.fullmatch(r"[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}", postcode):
        raise WebError("invalid_address")
    value["postcode"] = postcode[:-3] + " " + postcode[-3:]
    display = ", ".join(
        filter(
            None,
            [
                value.get("flat"),
                value.get("building"),
                value.get("house_number"),
                value.get("street"),
                value.get("town"),
                value.get("postcode"),
            ],
        )
    )
    if (
        not value.get("street")
        or not value.get("town")
        or not value.get("postcode")
        or not any(value.get(k) for k in ("flat", "building", "house_number"))
    ):
        raise WebError("invalid_address")
    location = await availability.geocode(display, expected_postcode=value["postcode"])
    snapshot = {
        **value,
        "latitude": location["lat"],
        "longitude": location["lng"],
        "display": display,
    }
    await query(
        "UPDATE web_session_meta SET address=%s WHERE thread_id=%s AND cust_id=%s",
        (Jsonb(snapshot), thread_id, cust_id),
    )
    return {"ok": True}


def fingerprint(req, address_snapshot):
    data = req.model_dump(mode="json") | {"address": address_snapshot}
    return hashlib.sha256(
        json.dumps(
            data, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


async def create(req, key):
    co = await session(req.thread_id, req.cust_id)
    if co["rest_ref"] != req.rest_ref:
        raise WebError("invalid_request")
    # Recheck pause even when retrying. Reading/tracking does not use this switch.
    row = await availability.available(req.rest_ref, co["mode"])
    addr = co.get("address") if co["mode"] == "delivery" else None
    if co["mode"] == "delivery" and not addr:
        raise WebError("invalid_address")
    payment_mode = "live"
    if req.test_payment:
        if not (await is_test_payment_allowed(req.cust_id, req.rest_ref))[0]:
            raise WebError("test_payment_not_allowed", 403)
        payment_mode = "test"
    body_hash = fingerprint(req, addr)
    total = sum((item.price * item.quantity for item in req.order_items), Decimal(0))
    if total <= 0 or total > 10000:
        raise WebError("invalid_request")
    minimum = 0
    if addr:
        option = await availability.pricing(
            row, {"lat": addr["latitude"], "lng": addr["longitude"]}
        )
        minimum = option["minimum_order_value"]
        if total < Decimal(str(minimum)):
            raise WebError("below_minimum", min_order_value=minimum)
    pool = await pg_settings.get_pool()
    async with pool.connection() as conn:
        async with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SET LOCAL search_path = public")
            await cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("web:" + key,)
            )
            await cur.execute(
                "SELECT * FROM web_order_request WHERE idempotency_key=%s", (key,)
            )
            attempt = await cur.fetchone()
            if attempt:
                if (
                    attempt["thread_id"] != req.thread_id
                    or attempt["body_hash"] != body_hash
                ):
                    raise WebError("idempotency_conflict", 409)
            else:
                # Bound abandoned orders per checkout; idempotent retries do not consume this budget.
                await cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    ("web-thread:" + req.thread_id,),
                )
                await cur.execute(
                    "SELECT count(*) AS n FROM web_order_request WHERE thread_id=%s",
                    (req.thread_id,),
                )
                if (await cur.fetchone())["n"] >= 10:
                    raise WebError("rate_limited", 429)
                # Each order has its own W-id: later checkout edits cannot change
                # the address that init_delivery reads after Stripe authorises.
                customer = new_web_customer_key()
                await cur.execute(
                    """INSERT INTO customer_master(cust_id,cust_name,house_number,building_name,street_name,city,postcode,lat,lon)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        customer,
                        customer,
                        (addr or {}).get("house_number"),
                        " ".join(
                            filter(
                                None,
                                [
                                    (addr or {}).get("flat"),
                                    (addr or {}).get("building"),
                                ],
                            )
                        )
                        or None,
                        (addr or {}).get("street"),
                        (addr or {}).get("town"),
                        (addr or {}).get("postcode"),
                        (addr or {}).get("latitude"),
                        (addr or {}).get("longitude"),
                    ),
                )
                day = utcnow().astimezone(availability.UK).date()
                await cur.execute("SELECT get_next_daily_seq(%s) AS seq", (day,))
                seq = (await cur.fetchone())["seq"]
                reference = new_order_reference(customer, day.isoformat())
                order_id, order_number = (
                    f"{reference}-{seq}",
                    f"{req.rest_ref}-{reference}-{seq}",
                )
                instructions = (addr or {}).get("instructions")
                notes = (
                    "\n".join(
                        filter(
                            None,
                            [
                                req.notes,
                                f"Delivery instructions: {instructions}"
                                if instructions
                                else None,
                            ],
                        )
                    )
                    or None
                )
                payload = {
                    "order_id": order_id,
                    "order_number": order_number,
                    "seq_id": seq,
                    "recipient": customer,
                    "thread_id": req.thread_id,
                    "action": "delivery" if co["mode"] == "delivery" else "takeaway",
                    "total_price": float(total),
                    "payment_status": "requires_payment",
                    "origin_channel": "web",
                    "storefront": "ordelo",
                    "payment_mode": payment_mode,
                    "idempotency_key": key,
                    "notes": notes,
                }
                await cur.execute(
                    "SELECT create_food_order_with_items(%s,%s)",
                    (
                        Jsonb(payload),
                        Jsonb([i.model_dump(mode="json") for i in req.order_items]),
                    ),
                )
                await cur.execute(
                    "INSERT INTO web_order_request(idempotency_key,thread_id,body_hash,order_number,address) VALUES (%s,%s,%s,%s,%s)",
                    (key, req.thread_id, body_hash, order_number, Jsonb(addr)),
                )
                attempt = {"order_number": order_number, "quote": None}
        # The order is now durable. Failed/ambiguous external calls never cause
        # another order; only a missing payment URL may be regenerated (D22).
        async with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SET LOCAL search_path = public")
            await cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("web:" + key,)
            )
            await cur.execute(
                "SELECT quote FROM web_order_request WHERE idempotency_key=%s", (key,)
            )
            quote = (await cur.fetchone())["quote"]
            if not quote:
                food = await asyncio.to_thread(
                    FoodOrder.from_order_number, attempt["order_number"]
                )
                if food is None or food.final_order_value is None:
                    raise WebError("pricing_unavailable", 503)
                generator = (
                    generate_payment_intent_url
                    if food.action == "delivery"
                    else generate_takeaway_manual_payment_url
                )
                url = await generator(food)
                if not url:
                    raise WebError("payment_unavailable", 503)
                quote = {
                    "order_number": food.order_number,
                    "order_id": food.order_id,
                    "items_total": float(total),
                    "service_charge": food.service_charge or 0,
                    "delivery_fee": food.delivery_fee or 0,
                    "small_order_fee": food.small_order_fee or 0,
                    "total": food.final_order_value,
                    "min_order_value": minimum,
                    "payment_url": url,
                    "payment_mode": "test" if food.uses_test_payment else "live",
                    # This is Ordelo's acceptance window, not Stripe Session expiry.
                    "payment_accept_by": iso(await _accept_by(cur, food.order_number)),
                }
                await cur.execute(
                    "UPDATE web_order_request SET quote=%s WHERE idempotency_key=%s",
                    (Jsonb(quote), key),
                )
    token = await order_access.issue(attempt["order_number"])
    return {
        **quote,
        "access": {
            "token": token,
            "page_path": f"/town/{co['town_slug']}/orders/{attempt['order_number']}",
        },
    }


async def _accept_by(cur, order_number):
    await cur.execute(
        "SELECT order_dtts+interval '35 minutes' AS at FROM food_order WHERE order_number=%s",
        (order_number,),
    )
    return (await cur.fetchone())["at"]
