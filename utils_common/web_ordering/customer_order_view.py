"""Read-only R3 order views derived from fulfilment and verified payment events.

Never infer capture/release from food_order.requires_capture, which remains
unchanged after existing payment-service operations. Redact before returning.

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . delivery_dispatch (table, ordelo_datamodels/dispatch/delivery_dispatch.sql): reads (SQL)
  . delivery_summary (table, ordelo_datamodels/delivery/delivery_summary.sql): named in code (passed to a query helper)
  . food_order (table, restaurant-agents): reads (SQL)
  . order_customer_event (table, ordelo_datamodels/notifications/order_customer_event.sql): reads (SQL)
  . order_item (table, restaurant-agents): reads (SQL)
  . restaurant_master (table, ordelo_datamodels/core/restaurant_master.sql): reads (SQL)
  . rider_master (table, ordelo_datamodels/core/rider_master.sql): reads (SQL)
  . takeaway_summary (table, ordelo_datamodels/takeaway/takeaway_summary.sql): named in code (passed to a query helper)
  . web_order_request (table, ordelo_datamodels/ordering/web_order_request.sql): reads (SQL)
  . web_payment_release (table, ordelo_datamodels/ordering/web_payment_release.sql): reads (SQL)
(end of database objects)
"""

from urllib.parse import quote
from datetime import timedelta
from utils_common.payment_ms.return_urls import wa_chat_url
from .common import RESTAURANTS, WebError, one, query, iso, utcnow

EVENT_TYPES = {
    "payment_authorised",
    "restaurant_accepted",
    "pickup_time_set",
    "pickup_time_updated",
    "rider_assigned",
    "food_collected",
    "rider_near_customer",
    "delivered",
    "no_rider_found",
    "restaurant_declined",
    "ready_for_collection",
    "collected",
    "payment_captured",
    "payment_released",
}


def derive(food, summary, dispatch, events, release=None, at=None):
    """Derive (display_status, payment_state, captured, cancel_reason) from evidence.

    This pure projection prioritizes rejection/release over fulfilment progress.
    Capture needs a customer capture event; release needs a completed release job
    or cancellation evidence. requires_capture alone proves neither outcome.
    Use at for deterministic evaluation of the 35-minute unpaid-order window.
    """
    types = {e["event_type"] for e in events}
    data = [e.get("data", {}).get("payload", {}) for e in events]
    captured = "payment_captured" in types
    released = (
        bool((release or {}).get("completed_at"))
        or "payment_released" in types
        or any(p.get("payment_cancelled") is True for p in data)
    )
    rejected = (
        released
        or summary.get("status") in ("declined", "timedout", "cancelled")
        or bool(release)
        or bool(types & {"no_rider_found", "restaurant_declined"})
    )
    authorised = (
        food["payment_status"] != "requires_payment" or "payment_authorised" in types
    )
    if rejected:
        state = (
            "released"
            if released
            else "refund_pending"
            if captured
            else "release_pending"
        )
        reason = (
            "no_rider_found"
            if summary.get("status") == "timedout" or "no_rider_found" in types
            else "restaurant_declined"
            if "restaurant_declined" in types or summary.get("status") == "declined"
            else "cancelled_by_restaurant"
        )
        return "cancelled", state, captured, reason
    if summary.get("status") == "completed" or types & {"delivered", "collected"}:
        status = "delivered" if food["action"] == "delivery" else "collected"
    elif dispatch.get("status") == "pickedup" or "food_collected" in types:
        status = "on_its_way"
    elif (
        dispatch.get("status") == "assigned"
        or summary.get("status") == "assigned"
        or "rider_assigned" in types
    ):
        status = "rider_assigned"
    elif "ready_for_collection" in types:
        status = "ready_for_collection"
    elif summary.get("pickup_time") or summary.get(
        "restaurant_confirmation_status"
    ) in ("restaurant_accept", "auto_accept", "restaurant_pickuptime_adjusted"):
        status = "preparing"
    elif authorised:
        status = "waiting_for_restaurant"
    elif (at or utcnow()) > food["order_dtts"] + timedelta(minutes=35):
        status = "payment_not_completed"
    else:
        status = "confirming_payment"
    state = (
        "captured"
        if captured
        else "authorised"
        if authorised
        else "not_completed"
        if status == "payment_not_completed"
        else "pending"
    )
    return status, state, captured, None


async def get_view(order_number, detail_level="full"):
    """Assemble a read-only customer DTO for a registered web or WhatsApp order.

    Combine FoodOrder, summary, latest relevant dispatch, events and release job.
    Full grants add address/items/charges and the delivery code at appropriate
    stages; other detail levels omit those fields. Expose only the rider's first
    name. Raise not_found for absent orders or unknown registry refs.
    Authorization belongs to the caller; separate reads are not one DB snapshot.
    """
    food = await one(
        "SELECT * FROM food_order WHERE order_number=%s AND origin_channel IN ('web','whatsapp')",
        (order_number,),
    )
    if not food:
        raise WebError("not_found", 404)
    rest_ref = order_number.split("-")[0]
    registry = RESTAURANTS.get(rest_ref)
    if not registry:
        raise WebError("not_found", 404)
    restaurant = await one(
        "SELECT * FROM restaurant_master WHERE rest_ref=%s", (rest_ref,)
    )
    summary = (
        await one(
            "SELECT * FROM "
            + (
                "delivery_summary"
                if food["action"] == "delivery"
                else "takeaway_summary"
            )
            + " WHERE order_number=%s",
            (order_number,),
        )
        or {}
    )
    dispatch = (
        await one(
            "SELECT * FROM delivery_dispatch WHERE order_number=%s AND status IN ('assigned','pickedup','completed') ORDER BY dispatch_id DESC LIMIT 1",
            (order_number,),
        )
        or {}
    )
    events = await query(
        "SELECT * FROM order_customer_event WHERE order_number=%s ORDER BY id",
        (order_number,),
    )
    release = await one(
        "SELECT * FROM web_payment_release WHERE order_number=%s", (order_number,)
    )
    status, payment, captured, reason = derive(food, summary, dispatch, events, release)
    address = ", ".join(
        str(restaurant[k])
        for k in ("house_number", "building_name", "street_name", "city", "postcode")
        if restaurant.get(k)
        and str(restaurant[k]).strip().lower()
        not in {"dummy", "test", "n/a", "unknown"}
    )
    times = [food["order_dtts"]] + [e["occurred_at"] for e in events]
    for key in ("restaurant_update_dtts", "dtts", "redispatch_dtts"):
        if summary.get(key):
            times.append(summary[key])
    if release:
        times.append(release["updated_at"])
    view = {
        "order_number": order_number,
        "origin_channel": food["origin_channel"],
        "mode": "delivery" if food["action"] == "delivery" else "collection",
        "detail_level": detail_level,
        "display_status": status,
        "last_event_id": max((e["id"] for e in events), default=0),
        "updated_at": iso(max(times)),
        "placed_at": iso(food["order_dtts"]),
        "payment": {"state": payment, "captured": captured},
        "restaurant": {
            "rest_ref": rest_ref,
            "name": restaurant["rest_name"],
            "phone": registry["phone"],
            "address": address,
            "map_url": "https://www.google.com/maps/search/?api=1&query="
            + quote(address),
        },
        "timeline": [
            {"type": e["event_type"], "at": iso(e["occurred_at"])}
            for e in events
            if e["event_type"] in EVENT_TYPES
        ],
        "support": {
            "call_restaurant": "tel:" + registry["phone"],
            "whatsapp_available": False,
        },
        "page_path": f"/town/{registry['town']}/orders/{order_number}",
    }
    if food["origin_channel"] == "whatsapp":
        wa_url = wa_chat_url(rest_ref)
        view["support"]["whatsapp_available"] = bool(wa_url)
        if wa_url:
            view["support"]["whatsapp_url"] = wa_url
    if reason:
        view["cancel_reason"] = reason
    if summary.get("pickup_time"):
        view["pickup_time"] = {
            "at": iso(summary["pickup_time"]),
            "is_estimate": summary.get("restaurant_confirmation_status")
            not in (
                "restaurant_accept",
                "auto_accept",
                "restaurant_pickuptime_adjusted",
            ),
            "updated": summary.get("restaurant_confirmation_status")
            == "restaurant_pickuptime_adjusted",
        }
    if detail_level == "full":
        request = (
            await one(
                "SELECT address FROM web_order_request WHERE order_number=%s",
                (order_number,),
            )
            if food["origin_channel"] == "web"
            else None
        ) or {}
        snapshot = request.get("address") or {}
        if food["action"] == "delivery":
            view["delivery"] = {
                "address": summary.get("customer_address")
                or snapshot.get("display", ""),
                "instructions": snapshot.get("instructions"),
            }
            if (
                status in ("rider_assigned", "on_its_way")
                and summary.get("cust_confirmation_code") is not None
            ):
                view["delivery"]["customer_code"] = str(
                    summary["cust_confirmation_code"]
                )
            if dispatch.get("rider_id"):
                rider = await one(
                    "SELECT rider_name FROM rider_master WHERE rider_id=%s",
                    (dispatch["rider_id"],),
                )
                if rider and rider.get("rider_name"):
                    view["delivery"]["rider_first_name"] = rider["rider_name"].split()[
                        0
                    ]
        items = await query(
            "SELECT product_name,quantity,price,modifications FROM order_item WHERE order_id=%s",
            (food["order_id"],),
        )
        view["items"] = [
            {
                "name": i["product_name"],
                "quantity": i["quantity"],
                "price": i["price"],
                "modifications": i.get("modifications") or [],
            }
            for i in items
        ]
        view["charges"] = {
            "items_total": food["total_price"],
            "discount": 0,
            "service_charge": food.get("service_charge") or 0,
            "delivery_fee": food.get("delivery_fee") or 0,
            "small_order_fee": food.get("small_order_fee") or 0,
            "total": food.get("final_order_value")
            if food.get("final_order_value") is not None
            else food["total_price"],
        }
        view["notes"] = food.get("notes")
    return view
