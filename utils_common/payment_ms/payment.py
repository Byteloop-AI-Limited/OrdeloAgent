"""
Payment microservice utilities for Stripe integration
    . Provides functions to generate, cancel, and capture Stripe payment intents for food orders
    . Constructs payment URLs based on order and thread IDs
    . Generates order summaries including order items and fees for payment processing
    . Integrates with Supabase for order item retrieval
    . Uses httpx for async HTTP requests to Stripe endpoints
    . Centralizes logging and configuration via ms_settings and logger
    . Optional return_urls ({"success_url", "cancel_url"}) are added to the payload when given;
      without them the payload is unchanged and the payment service uses its per-restaurant defaults
  Functions/Classes:
    . get_payment_uri
    . generate_payment_intent
    . generate_takeaway_manual_payment_url
    . generate_automatic_payment_url
    . cancel_payment
    . capture_payment
    . generate_order_summary_for_payment_intent
"""

# %%
import httpx
from config import ms_settings, logger
from utils_common.order_management.food_order_pymodel import FoodOrder


# %%
async def generate_payment_intent_url(
    food_order: FoodOrder, return_urls: dict[str, str] | None = None
):
    """
    Generates a Stripe payment intent for a given order.

    Args:
        food_order: A FoodOrder instance containing order details.
        return_urls: Optional {"success_url", "cancel_url"} for the Checkout Session.

    Returns:
        A string representing the Stripe payment intent URL.
    """
    payment_uri = food_order.payment_uri
    intent_payload = await food_order.gen_payment_intent_payload()
    if return_urls:
        intent_payload.update(return_urls)

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
async def generate_automatic_payment_url(
    food_order: FoodOrder, is_print_only: bool = False
):
    """
    Generates a Stripe payment URL for automatic capture or a print-only job.

    Args:
        food_order: A FoodOrder instance containing order details.

    Returns:
        A string representing the Stripe payment URL, or None if an error occurred.
    """
    return await _generate_takeaway_payment_url(
        food_order,
        manual_mode_capture=False,
        is_print_only=is_print_only,
    )


async def generate_takeaway_manual_payment_url(
    food_order: FoodOrder, return_urls: dict[str, str] | None = None
):
    """Creates a manual-capture Checkout Session for an online takeaway order."""
    return await _generate_takeaway_payment_url(
        food_order,
        manual_mode_capture=True,
        is_print_only=False,
        return_urls=return_urls,
    )


async def _generate_takeaway_payment_url(
    food_order: FoodOrder,
    *,
    manual_mode_capture: bool,
    is_print_only: bool,
    return_urls: dict[str, str] | None = None,
):
    """Posts the shared product-only takeaway payment payload."""
    payment_uri = food_order.payment_uri
    order_summary = await food_order.generate_product_order_summary()

    intent_payload = {
        "total_amount": order_summary.get("total"),
        "items": order_summary.get("items"),
        "currency": "GBP",
        "action": "collection",
        "restaurant_confirmation_code": "N/A",
        "manual_mode_capture": manual_mode_capture,
        "notes": food_order.notes,
        "printonlyjob": is_print_only,
        "restRef": food_order.rest_ref,
    }
    if return_urls:
        intent_payload.update(return_urls)

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(
                payment_uri, json=intent_payload, headers=ms_settings.stripe_headers
            )
            res.raise_for_status()
            return res.json()["url"]
        except httpx.HTTPError as e:
            logger.error(f"Error during takeaway payment intent creation: {e}")
            return None


# # %% Create similar function for cancel payment intent and capture payment intent called cancel_payment and capture_payment


# %%
"""
# Test the generate_automatic_payment_url function.
# %%

test_order_number = "CHKS-FIRC-30"
food_order = FoodOrder.from_order_number(test_order_number)
payment_uri = food_order.payment_uri
# order_summary = await food_order.generate_order_summary_for_automatic_payment()

payment_url = await generate_automatic_payment_url(food_order, is_print_only=True)

# payment_url
# %%


"""
