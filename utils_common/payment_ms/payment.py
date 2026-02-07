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
from config import ms_settings, logger
from utils_common.order_management.food_order_pymodel import FoodOrder


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
    Generates a Stripe payment URL for automatic capture (No manual_mode, instant capture on stripe for takeaways.).

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


# # %% Create similar function for cancel payment intent and capture payment intent called cancel_payment and capture_payment
