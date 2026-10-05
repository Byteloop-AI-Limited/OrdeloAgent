"""
Which orders use Stripe test mode (plan D32, simplified by R3.1 / D35).

  . Every order for a restaurant listed in ``ordelo_config.TEST_PAYMENT_REST_REFS``
    is a test payment, requested or not. That list is the one payment switch.
  . On any other restaurant an overwatch recipient can request a test payment
    with ``?isTest3100=true`` (WhatsApp orders carry the customer's number).
  . Everyone else pays live, so adding the parameter to a URL can never let a
    real customer pay with Stripe's test card.

Functions:
  . resolve_payment_mode - ("test" | None, reason) for an order being created
"""

import asyncio

from config import logger
from config.feature_flags import TEST_PAYMENT_REST_REFS, config_csv
from config.params import get_overwatch_list


async def _is_overwatch(recipient: str) -> bool:
    try:
        overwatch = await asyncio.to_thread(get_overwatch_list)
    except Exception as err:  # no list means "not overwatch"
        logger.warning(f"test payment: overwatch list unavailable: {err}")
        return False
    return recipient in overwatch


async def resolve_payment_mode(recipient: str, rest_ref: str, requested: bool) -> tuple[str | None, str]:
    """``("test", reason)`` for a test payment, else ``(None, reason)`` (live).

    ``None`` keeps ``food_order.payment_mode`` unset so today's overwatch +
    delivery rule in ``FoodOrder.uses_test_payment`` still applies. A failed
    lookup of the test list raises: a test restaurant must never silently take
    a live payment.
    """
    try:
        test_refs = await config_csv(TEST_PAYMENT_REST_REFS, fail_on_error=True)
    except Exception:
        logger.error(f"payment mode: {TEST_PAYMENT_REST_REFS} lookup failed; refusing order rest_ref={rest_ref}")
        raise
    if rest_ref.upper() in test_refs:
        return "test", "test_restaurant"
    if not requested:
        return None, "not_requested"
    if await _is_overwatch(recipient):
        return "test", "overwatch_recipient"
    return None, "not_allowed"
