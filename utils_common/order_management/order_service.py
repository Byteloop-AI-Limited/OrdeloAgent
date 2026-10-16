"""
Order services for WhatsApp automation
  . Provides reusable helpers for order pricing lookups
  . Retrieves minimum order value from database or pricing service fallback
  . Resolves restaurant coordinates via explicit values or rest_ref lookup
  . Generates minimum order value messages based on coordinates
  . Creates food orders atomically; the RPC fixes TEST3100-derived payment mode
  . Captures payments for orders using Stripe payment microservice
  . Integrates with Supabase for order persistence and httpx for async HTTP
Functions/Classes:
  . _call_pricing_service - Calls pricing microservice
  . _resolve_restaurant_coordinates - Resolves restaurant coordinates
  . get_min_order_value_for_location - Builds delivery message for customer location
  . get_min_order_value - Fetches minimum order value for an order
  . create_order_with_items - Creates order and order items in one transaction (RPC)
  . capture_payment_for_order - Captures payment for order with restaurant confirmation
    . Routes customer notifications through the R1b notifier

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . create_food_order_with_items (function, ordelo_datamodels/ordering/create_food_order_with_items.sql): calls, calls (name passed to a helper)
  . get_next_daily_seq (function, restaurant-agents): calls, calls (name passed to a helper)
  . restaurant_master (table, ordelo_datamodels/core/restaurant_master.sql): reads, named in code (passed to a query helper)
(end of database objects)
"""

# %%
from __future__ import annotations

from utils_common.notify import customer_notifier

import asyncio
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

import requests
import uuid
from config import client_ordelo, logger, ms_settings

from utils_common.order_management.order_db_ops_new import OrderItem
from utils_common.order_management.order_reference import (
    is_phone_derived,
    new_order_reference,
)


# %%


def _call_pricing_service(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Call pricing microservice and return parsed JSON on success."""
    url = ms_settings.pricing_url
    headers = {"Content-Type": "application/json"}
    payload["order_number"] = str(uuid.uuid4())
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"Pricing service HTTP error: {http_err}")
    except requests.exceptions.RequestException as req_err:
        logger.error(f"Pricing service request error: {req_err}")
    except Exception as err:  # noqa: BLE001 - capture unexpected issues
        logger.exception(f"Unexpected error calling pricing service: {err}")
    return None


def _resolve_restaurant_coordinates(
    rest_lat: Optional[float], rest_lon: Optional[float], rest_ref: Optional[str]
) -> Tuple[float, float]:
    """Return restaurant coordinates using explicit values or rest_ref lookup."""
    if rest_lat is not None and rest_lon is not None:
        return rest_lat, rest_lon

    if rest_ref:
        response = (
            client_ordelo.table("restaurant_master")
            .select("lat, lon")
            .eq("rest_ref", rest_ref.upper())
            .execute()
        )
        records = response.data if response else []
        if not records:
            raise ValueError(f"Restaurant with ref '{rest_ref}' not found")

        record = records[0]
        lat = record.get("lat")
        lon = record.get("lon")
        if lat is None or lon is None:
            raise ValueError(
                f"Restaurant '{rest_ref}' does not have lat/lon coordinates configured"
            )

        return float(lat), float(lon)

    raise ValueError(
        "rest_ref is required when restaurant coordinates are not provided"
    )


def get_min_order_value_for_location(
    cust_lat: float,
    cust_lon: float,
    *,
    rest_lat: Optional[float] = None,
    rest_lon: Optional[float] = None,
    rest_ref: Optional[str] = None,
) -> str:
    """Return human-readable minimum order value message for lat/lon pair."""
    restaurant_lat, restaurant_lon = _resolve_restaurant_coordinates(
        rest_lat, rest_lon, rest_ref
    )

    payload = {
        "total_food_value": 0,
        "restaurant_latitude": restaurant_lat,
        "restaurant_longitude": restaurant_lon,
        "customer_latitude": cust_lat,
        "customer_longitude": cust_lon,
        "rest_ref": rest_ref,
    }

    response_json = _call_pricing_service(payload)
    if not response_json:
        return ""

    message_parts: list[str] = []
    for option in response_json.get("delivery_options", []):
        if option.get("vehicle_type") == "car":
            message_parts.append(option.get("message", ""))

    return "".join(message_parts)


def get_min_order_value(
    cust_lat: float,
    cust_lon: float,
    *,
    rest_lat: Optional[float] = None,
    rest_lon: Optional[float] = None,
    rest_ref: Optional[str] = None,
) -> Optional[float]:
    """Retrieve minimum order value for order number, falling back to pricing service."""
    restaurant_lat, restaurant_lon = _resolve_restaurant_coordinates(
        rest_lat, rest_lon, rest_ref
    )
    records: list[dict[str, Any]] = []
    # if order_number:
    #     delivery_option = (
    #         client_ordelo.table("delivery_option")
    #         .select("*")
    #         .eq("order_number", order_number)
    #         .eq("vehicle_type", "car")
    #         .execute()
    #     )

    #     records = delivery_option.data if delivery_option else []
    #     if records:
    #         return records[0].get("min_order_value")

    payload = {
        "total_food_value": 0,
        "restaurant_latitude": restaurant_lat,
        "restaurant_longitude": restaurant_lon,
        "customer_latitude": cust_lat,
        "customer_longitude": cust_lon,
        "rest_ref": rest_ref,
    }
    response_json = _call_pricing_service(payload)
    if not response_json:
        return -1

    for option in response_json.get("delivery_options", []):
        if option.get("vehicle_type") == "car":
            return option.get("minimum_order_value")

    # return -1
    # response_json = _call_pricing_service(payload)
    # min_order_value = response_json.get("minimum_order_value")

    # return float(min_order_value)


ORIGIN_CHANNELS = ("whatsapp", "web")
STOREFRONTS = ("direct", "ordelo")
_MAX_REFERENCE_ATTEMPTS = 3


def _is_duplicate_key_error(error_message: str) -> bool:
    """True when a Postgres error is a unique violation (e.g. order_id collision)."""
    return "duplicate key" in error_message or "23505" in error_message


async def _insert_order_rpc(
    insert_payload: Dict[str, Any], order_items: List[OrderItem]
) -> Dict[str, Any]:
    """F4: insert food_order and order_item in one transaction (SQL RPC)."""
    order_id = insert_payload["order_id"]
    items = [
        item.model_dump(include={"product_name", "sku", "quantity", "price", "modifications"})
        for item in order_items
    ]
    try:
        await asyncio.to_thread(
            lambda: client_ordelo.rpc(
                "create_food_order_with_items",
                {"p_order": insert_payload, "p_items": items},
            ).execute()
        )
    except Exception as e:
        error_message = str(e)
        logger.error(f"Error creating order {order_id} via RPC: {error_message}")
        return {
            "success": False,
            "error": "Failed to create order",
            "details": error_message,
            "duplicate_order_id": _is_duplicate_key_error(error_message),
        }
    return {"success": True}


async def create_order_with_items(
    recipient: str,
    thread_id: str,
    order_items: List[OrderItem],
    rest_ref: str,
    action: str,
    notes: Optional[str] = None,
    origin_channel: str = "whatsapp",
    storefront: str = "direct",
) -> Dict[str, Any]:
    """
    Creates a new food order with order items in the database.

    Args:
        recipient: Customer key (WhatsApp number, or a W-id for a web order)
        thread_id: WhatsApp thread ID, or the web thread for a web order
        order_items: List of OrderItem objects
        rest_ref: Restaurant reference code
        action: "delivery" or "takeaway"
        notes: Optional order notes
        origin_channel: "whatsapp" (default) or "web" (plan D29)
        storefront: "direct" (default) or "ordelo" (plan D28)

    Returns:
        Dict with success status, order_id, order_number, or error details
    """
    if origin_channel not in ORIGIN_CHANNELS:
        return {"success": False, "error": f"Invalid origin_channel: {origin_channel}"}
    if storefront not in STOREFRONTS:
        return {"success": False, "error": f"Invalid storefront: {storefront}"}

    order_dt: str = datetime.now().strftime("%Y-%m-%d")

    # Calculate total price from order items
    total_price = sum(item.price * item.quantity for item in order_items)

    # Get next sequence number
    try:
        seq_number = await asyncio.to_thread(
            lambda: client_ordelo.rpc(
                "get_next_daily_seq", {"input_date": order_dt}
            ).execute()
        )
    except Exception as e:
        error_message = str(e)
        logger.error(f"Error getting sequence number: {error_message}")
        return {
            "success": False,
            "error": "Failed to get sequence number",
            "details": error_message,
        }

    # A phone-derived reference is deterministic, so retrying can't help;
    # a random one (W-ids) is retried on an order_id collision.
    attempts = 1 if is_phone_derived(recipient) else _MAX_REFERENCE_ATTEMPTS

    result: Dict[str, Any] = {"success": False, "error": "Order not created"}
    for attempt in range(1, attempts + 1):
        order_reference = new_order_reference(recipient, order_dt)
        order_id = f"{order_reference}-{seq_number.data}"
        order_number = f"{rest_ref.upper()}-{order_reference}-{seq_number.data}"

        insert_payload = {
            "order_id": order_id,
            "order_number": order_number,
            "seq_id": seq_number.data,
            "recipient": recipient,
            "notes": notes,
            "thread_id": thread_id,
            "action": action,
            "total_price": total_price,
            "payment_status": "requires_payment",
        }
        # Written only when not the default, so WhatsApp inserts are unchanged
        # and still work before the R1 SQL has been run.
        if origin_channel != "whatsapp":
            insert_payload["origin_channel"] = origin_channel
        if storefront != "direct":
            insert_payload["storefront"] = storefront

        result = await _insert_order_rpc(insert_payload, order_items)

        if result.get("success"):
            await customer_notifier.create_origin_subscription(order_number)
            return {"success": True, "order_id": order_id, "order_number": order_number}
        if not result.get("duplicate_order_id") or attempt == attempts:
            break
        logger.warning(
            f"order_id {order_id} already exists; retrying with a new reference "
            f"(attempt {attempt + 1}/{attempts})"
        )

    result.pop("duplicate_order_id", None)
    return result

# %%
""" Test
payload = {
    "total_food_value": 0,
    "restaurant_latitude": 51.0717612607721,
    "restaurant_longitude": -1.79609677126815,
    "customer_latitude": 51.0439463,
    "customer_longitude": -1.7898225,
    "rest_ref": "sfcs",
}

result = _call_pricing_service(payload)
print(result)



# %%
payload = {
        "order_number": "sfcs-12545",
        "total_food_value": 20,
        "restaurant_latitude": 51.0717612607721,
        "restaurant_longitude": -1.79609677126815,
        "customer_latitude": 51.0439463,
        "customer_longitude": -1.7898225,
        "rest_ref": "SFCS",
    }

# payload = {
#         "order_number": "SFCS-123",
#         "total_food_value": 20,
#         "restaurant_latitude": 51.0717612607721,
#         "restaurant_longitude": -1.79609677126815,
#         "customer_latitude": 51.0716352,
#         "customer_longitude": -1.796063,
#     }

url = ms_settings.pricing_url
headers = {"Content-Type": "application/json"}

response = requests.post(url, json=payload, headers=headers)
if response.status_code != 200:
    print(response.status_code, response.text)
else:
    response_json = response.json()
    print(response_json)

# %%

"""
