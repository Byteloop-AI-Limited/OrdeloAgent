"""R3 web sessions and durable idempotent checkout using existing order/payment contracts.

Order + request + address snapshot commit atomically before external payment I/O.
A transaction advisory lock serializes payment-URL retries across processes.
Client unit prices/discounts remain the explicitly accepted D8 risk.

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . create_food_order_with_items (function, ordelo_datamodels/ordering/create_food_order_with_items.sql): calls (SQL)
  . create_thread (function, restaurant-agents): calls (SQL)
  . customer_master (table, ordelo_datamodels/core/customer_master.sql): writes (SQL)
  . food_order (table, restaurant-agents): reads (SQL)
  . get_next_daily_seq (function, restaurant-agents): calls (SQL)
  . web_order_request (table, ordelo_datamodels/ordering/web_order_request.sql): reads (SQL), writes (SQL)
  . web_session_meta (table, ordelo_datamodels/ordering/web_session_meta.sql): reads (SQL), writes (SQL)
(end of database objects)
"""

import asyncio
import hashlib
import json
from decimal import Decimal
from datetime import timedelta
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from loguru import logger
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from config.pg_setting import pg_settings
from utils_common.order_management.customer_keys import new_web_customer_key
from utils_common.order_management.order_reference import new_order_reference
from utils_common.order_management.food_order_pymodel import FoodOrder
from utils_common.payment_ms.payment import (
    generate_payment_intent_url,
    generate_takeaway_manual_payment_url,
)
from utils_common.payment_ms.return_urls import web_return_urls
from . import availability, order_access
from .common import (
    MAX_ORDER_LINES,
    RESTAURANTS,
    WebError,
    iso,
    normalise_postcode,
    one,
    postcode_sector,
    query,
    utcnow,
)


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
        """Validate each modifier display string is at most 200 characters.

        Return the original list or raise ValueError for an oversized entry.
        """
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
    client_estimate: dict[str, float | None] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_payment_request(cls, values):
        """Older cached clients may send this field; it has no routing effect."""
        if isinstance(values, dict):
            values = {key: value for key, value in values.items() if key != "test_payment"}
        return values

    @field_validator("client_estimate")
    @classmethod
    def finite_estimate(cls, values):
        """Reject non-finite or excessive client estimate values.

        Allow None and magnitudes up to 100000; these estimates are not price authority.
        """
        import math

        if any(
            value is not None and (not math.isfinite(value) or abs(value) > 100000)
            for value in values.values()
        ):
            raise ValueError("Invalid estimate")
        return values


async def start(rest_ref, mode, town_slug, visitor_id, district=None, postcode=None):
    """Create a two-hour WEB checkout session for a restaurant, mode and town.

    Recheck availability and town mapping, create a thread through create_thread,
    then persist web_session_meta with a synthetic checkout customer key.
    Return thread_id, cust_id and expiry. The thread and metadata writes are
    separate transactions; no rider or customer agent is started.

    A delivery session also stores the full approved postcode (ADR 0008): the
    backend's authority for the postcode-sector gate in address(). It must sit
    in the stated district (postcode_mismatch). A missing or malformed postcode
    is stored as NULL, which makes address() fail closed; collection stores NULL.
    """
    await availability.available(rest_ref, mode)
    if town_slug != RESTAURANTS[rest_ref]["town"]:
        raise WebError("unknown_town")
    postcode = normalise_postcode(postcode) if mode == "delivery" else None
    if postcode and district and postcode.split()[0] != district.upper().replace(" ", ""):
        raise WebError("postcode_mismatch")
    thread = await one("SELECT * FROM public.create_thread(%s,%s)", ("WEB", None))
    cust_id = new_web_customer_key()
    expiry = utcnow() + timedelta(hours=2)
    await query(
        """INSERT INTO web_session_meta(thread_id,visitor_id,cust_id,rest_ref,mode,town_slug,postcode_district,postcode,expires_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            thread["thread_id"],
            visitor_id,
            cust_id,
            rest_ref,
            mode,
            town_slug,
            district,
            postcode,
            expiry,
        ),
    )
    return {
        "thread_id": thread["thread_id"],
        "cust_id": cust_id,
        "expires_at": expiry.isoformat(),
    }


async def session(thread_id, cust_id):
    """Return unexpired checkout metadata matching both thread_id and cust_id.

    Raise no_checkout_session (409) when no matching unexpired checkout exists.
    """
    row = await one(
        "SELECT * FROM web_session_meta WHERE thread_id=%s AND cust_id=%s AND expires_at>now()",
        (thread_id, cust_id),
    )
    if not row:
        raise WebError("no_checkout_session", 409)
    return row


def address_display(value):
    """Join the customer's address parts into one line, skipping empty parts."""
    keys = ("flat", "building", "house_number", "street", "town", "postcode")
    return ", ".join(filter(None, (value.get(key) for key in keys)))


async def address(thread_id, cust_id, value):
    """Validate and save a delivery address on the checkout session (ADR 0008).

    Enforce field bounds and street/town; a house number or name is optional
    because some roads have none. For delivery the backend's stored postcode
    (web_session_meta.postcode, set at checkout start) is the authority: the
    request postcode is only compared, a different sector is postcode_mismatch,
    and a session with no stored postcode fails closed (409
    checkout_restart_required). The address text is never rejected by Google: the snapshot
    keeps the customer's text, the locked postcode's centroid for pricing and
    a best-effort rider pin with its precision. An order later copies this
    editable draft into its own immutable request snapshot.
    """
    meta = await session(thread_id, cust_id)
    allowed = {
        "flat": 40,
        "building": 60,
        "house_number": 20,
        "street": 80,
        "town": 60,
        "postcode": 10,
        "instructions": 200,
    }
    bad = [
        key
        for key, text in value.items()
        if key not in allowed
        or not isinstance(text, (str, type(None)))
        or (text is not None and len(text) > allowed[key])
    ]
    if bad:
        logger.warning("[web-addr] rejected: unknown/oversized/non-string fields={}", bad)
        raise WebError("invalid_address")
    value = {key: text.strip() for key, text in value.items() if isinstance(text, str)}
    sent = normalise_postcode(value.get("postcode"))
    if value.get("postcode") and not sent:
        raise WebError("invalid_address")
    if meta.get("mode") == "delivery":
        stored = meta.get("postcode")
        if not stored:
            # Sessions started before ADR 0008 (or by an older frontend) cannot
            # prove their sector: send the customer back to the postcode step.
            raise WebError("checkout_restart_required", 409)
        if sent and postcode_sector(sent) != postcode_sector(stored):
            logger.warning(
                "[web-addr] rejected: sector {!r} differs from checkout sector {!r}",
                postcode_sector(sent),
                postcode_sector(stored),
            )
            raise WebError("postcode_mismatch")
        value["postcode"] = stored
    else:
        if not sent:
            raise WebError("invalid_address")
        value["postcode"] = sent
    if not value.get("street") or not value.get("town"):
        raise WebError("invalid_address")
    display = address_display(value)
    located = await availability.locate(
        display,
        value["postcode"],
        street_address=address_display(
            {key: value.get(key) for key in ("street", "town", "postcode")}
        ),
    )
    logger.info("[web-addr] saved address pin_precision={}", located["precision"])
    snapshot = {
        **value,
        # The rider pin: customer_master.lat/lon for navigation (and the
        # shared fee calculation, bounded to the postcode sector).
        "latitude": located["pin"]["lat"],
        "longitude": located["pin"]["lng"],
        # The locked postcode's centroid: prices the minimum order.
        "postcode_latitude": located["centroid"]["lat"],
        "postcode_longitude": located["centroid"]["lng"],
        "pin_precision": located["precision"],
        "display": display,
    }
    await query(
        "UPDATE web_session_meta SET address=%s WHERE thread_id=%s AND cust_id=%s",
        (Jsonb(snapshot), thread_id, cust_id),
    )
    return {"ok": True}


def pricing_location(addr):
    """Coordinates that price the minimum order: the locked postcode's centroid.

    Snapshots saved before ADR 0008 only have the geocoded address point.
    """
    return {
        "lat": addr.get("postcode_latitude", addr["latitude"]),
        "lng": addr.get("postcode_longitude", addr["longitude"]),
    }


_PIN_NOTES = {
    "street": "Address not verified: map pin is on the street, not the door. Use the address text.",
    "postcode": "Address not verified: map pin is the postcode centre. Use the address text.",
}


def pin_note(addr):
    """Order note telling the restaurant and rider the map pin is approximate."""
    return _PIN_NOTES.get((addr or {}).get("pin_precision"))


def fingerprint(req, address_snapshot):
    """Hash canonical order input and its address snapshot with SHA-256.

    Include all serialized request fields so reuse of a key with changed input
    is detected. Reject non-finite JSON values rather than hashing them.
    """
    data = req.model_dump(mode="json") | {"address": address_snapshot}
    return hashlib.sha256(
        json.dumps(
            data, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def fingerprint_matches(stored_hash, req, address_snapshot):
    """Recognise old canonical hashes without using their toggle for routing.

    Only the retired field may differ. Every basket/address/identity field
    remains part of the comparison, including on pre-cutover cached quotes.
    """
    if stored_hash == fingerprint(req, address_snapshot):
        return True
    data = req.model_dump(mode="json") | {"address": address_snapshot}
    for old_value in (False, True):
        legacy = data | {"test_payment": old_value}
        candidate = hashlib.sha256(json.dumps(
            legacy, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()).hexdigest()
        if stored_hash == candidate:
            return True
    return False


async def create(req, key):
    """Create or resume an idempotent web order and return quote plus access grant.

    Validate session, availability, address, total and minimum; the creation RPC
    fixes payment mode from accepted item names.
    Under request/checkout advisory locks, atomically commit a fresh per-order
    W customer, FoodOrder/items and web_order_request. At most ten distinct
    requests are allowed per checkout; conflicting key/input returns 409.

    After that commit, serialize payment-URL generation with a second request
    lock and cache the quote. External failures leave the order durable for a
    retry with the same key; provider-session uniqueness is not guaranteed by
    this local lock. Accepted client item prices remain unchanged (decision D8).
    Issue a fresh order-access token even when returning a cached quote.
    """
    co = await session(req.thread_id, req.cust_id)
    if co["rest_ref"] != req.rest_ref:
        raise WebError("invalid_request")
    # Recheck pause even when retrying. Reading/tracking does not use this switch.
    row = await availability.available(req.rest_ref, co["mode"])
    addr = co.get("address") if co["mode"] == "delivery" else None
    if co["mode"] == "delivery" and not addr:
        raise WebError("invalid_address")
    body_hash = fingerprint(req, addr)
    total = sum((item.price * item.quantity for item in req.order_items), Decimal(0))
    if total <= 0 or total > 10000:
        raise WebError("invalid_request")
    minimum = 0
    if addr:
        option = await availability.pricing(row, pricing_location(addr))
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
                    or not fingerprint_matches(attempt["body_hash"], req, addr)
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
                                pin_note(addr),
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
        # Read outside the transaction so the config lookup never holds the advisory lock.
        # The secret order link is the Stripe success URL, so the grant must exist before the
        # payment URL is generated. Replays reuse the stored payment_url (and its first grant).
        token = await order_access.issue(attempt["order_number"])
        return_urls = await web_return_urls(attempt["order_number"], token)
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
                url = await generator(food, return_urls=return_urls)
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
    return {
        **quote,
        "access": {
            "token": token,
            "page_path": f"/town/{co['town_slug']}/orders/{attempt['order_number']}",
        },
    }


async def _accept_by(cur, order_number):
    """Read an order's creation time plus the 35-minute acceptance window.

    Use the caller's transaction cursor. This is Ordelo's authorisation deadline,
    not the hosted Stripe session's expiry.
    """
    await cur.execute(
        "SELECT order_dtts+interval '35 minutes' AS at FROM food_order WHERE order_number=%s",
        (order_number,),
    )
    return (await cur.fetchone())["at"]
