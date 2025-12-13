"""
Payment microservice utilities for Stripe integration
    . Provides functions to generate, cancel, and capture Stripe payment intents for food orders
    . Constructs payment URLs based on order and thread IDs
    . Generates order summaries including order items and fees for payment processing
    . Integrates with Supabase for order item retrieval
    . Uses httpx for async HTTP requests to Stripe endpoints
    . Centralizes logging and configuration via ms_settings and logger
  Functions/Classes:
    . get_payment_uri
    . generate_payment_intent
    . generate_automatic_payment_url
    . cancel_payment
    . capture_payment
    . generate_order_summary_for_payment_intent
"""

# %%
import httpx
from config import ms_settings, logger, client_ordelo
from utils_common.order_management.food_order_pymodel import FoodOrder

stripe_url = ms_settings.stripe_url

# %%


# %%
def get_payment_uri(order_id: str, thread_id: str) -> str:
    """
    Generates the payment URL for a given order based on thread_id and order_id.

    Args:
        thread_id: The ID of the WA thread
        order_id: orderId

    Returns:
        The constructed payment URL
    """
    return f"{stripe_url}/threads/{thread_id}/orders/{order_id}/payment-url"


# %%
async def generate_payment_intent_url(food_order: FoodOrder):
    """
    Generates a Stripe payment intent for a given order.

    Args:
        food_order: A FoodOrder instance containing order details.

    Returns:
        A string representing the Stripe payment intent URL.
    """
    payment_uri = food_order.payment_uri
    intent_payload = await food_order.gen_payment_intent_payload()
    logger.debug(f"Payment intent payload: {intent_payload}")

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                payment_uri, json=intent_payload, headers=ms_settings.stripe_headers
            )
            res.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            return res.json()["url"]
        except httpx.HTTPError as e:
            logger.error(f"Error during payment intent creation: {e}")
            return None


# %%
async def generate_automatic_payment_url(food_order: FoodOrder):
    """
    Generates a Stripe payment URL for automatic capture (no additional fees).

    Args:
        food_order: A FoodOrder instance containing order details.

    Returns:
        A string representing the Stripe payment URL, or None if an error occurred.
    """
    payment_uri = food_order.payment_uri
    order_summary = await food_order.generate_order_summary_for_automatic_payment()

    intent_payload = {
        "items": order_summary.get("items"),
        "currency": "GBP",
        "action": "collection",
        "manual_mode_capture": False,
        "notes": food_order.notes,
    }

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                payment_uri, json=intent_payload, headers=ms_settings.stripe_headers
            )
            res.raise_for_status()
            return res.json()["url"]
        except httpx.HTTPError as e:
            logger.error(f"Error during automatic payment intent creation: {e}")
            return None


# %% Create similar function for cancel payment intent and capture payment intent called cancel_payment and capture_payment


async def cancel_payment(order_id: str, thread_id: str):
    """
    Cancels a Stripe payment intent for a given order.

    Args:
        order_id: The ID of the order.
        thread_id: The ID of the WA thread associated with the order.

    Returns:
        The response JSON from the cancellation endpoint or None if an error occurred.
    """
    payment_uri = get_payment_uri(order_id=order_id, thread_id=thread_id)
    cancel_payload = {"action": "delivery", "payment_mode": "cancel"}
    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                payment_uri, json=cancel_payload, headers=ms_settings.stripe_headers
            )
            res.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            return res.text == ""
        except httpx.HTTPError as e:
            logger.error(f"Error during payment cancellation for order {order_id}: {e}")
            return False


# %%
async def capture_payment(order_id: str, thread_id: str):
    """
    Captures a Stripe payment intent for a given order.

    Args:
        order_id: The ID of the order.
        thread_id: The ID of the WA thread associated with the order.

    Returns:
        The response JSON from the capture endpoint or None if an error occurred.
    """
    payment_uri = get_payment_uri(order_id=order_id, thread_id=thread_id)
    capture_payload = {
        "action": "delivery",
        "payment_mode": "capture",
        "total_amount": 14.97,
    }

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                payment_uri, json=capture_payload, headers=ms_settings.stripe_headers
            )
            res.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            return res.text == ""
        except httpx.HTTPError as e:
            logger.error(f"Error during payment capture for order {order_id}: {e}")
            return False


# %%


async def generate_order_summary_for_payment_intent(food_order: FoodOrder):
    order_items = (
        client_ordelo.table("order_item")
        .select("""
            product_name, 
            quantity, 
            price
        """)
        .eq("order_id", food_order.order_id)
        .execute()
    )

    fee_items = [
        {
            "product_name": "Service Charge",
            "quantity": 1,
            "price": food_order.service_charge,
        },
        {
            "product_name": "Delivery Fee",
            "quantity": 1,
            "price": food_order.delivery_fee,
        },
        {
            "product_name": "Small Order Fee",
            "quantity": 1,
            "price": food_order.small_order_fee,
        },
    ]

    # Filter out fees with a price of 0
    fee_items = [item for item in fee_items if item["price"] > 0]
    all_items = order_items.data + fee_items
    order_summary = {"items": all_items}
    return order_summary


"""
# %% generate payment intent
order_id="ELAS-ZVEO-29"
# print(order_id)
food_order = FoodOrder.from_order_number(order_id)
order_summary = await generate_automatic_payment_url(food_order)
order_summary
# %%

await generate_payment_intent(order_summary)

"""
