"""
Test payments on request (plan D32).

A checkout can ask for a test payment with ``?isTest3100=true``; the front end
passes ``test_payment: true`` to create-order. Ordelo only honours it for:

  . an overwatch recipient (WhatsApp orders carry the customer's number), or
  . a restaurant listed in ``ordelo_config.TEST_PAYMENT_REST_REFS``
    (web orders carry no phone number, plan D24).

Anyone else gets a live payment, so adding the parameter to a URL can never
let a real customer pay with Stripe's test card.

Functions:
  . is_test_payment_allowed - (allowed, reason) for a recipient and restaurant
"""

import asyncio

from config import logger
from config.feature_flags import TEST_PAYMENT_REST_REFS, config_csv
from config.params import get_overwatch_list


async def is_test_payment_allowed(recipient: str, rest_ref: str) -> tuple[bool, str]:
    """Whether a requested test payment may be honoured, and why."""
    try:
        overwatch = await asyncio.to_thread(get_overwatch_list)
    except Exception as err:  # noqa: BLE001 - no list means "not overwatch"
        logger.warning(f"test payment: overwatch list unavailable: {err}")
        overwatch = []
    if recipient in overwatch:
        return True, "overwatch_recipient"
    if rest_ref.upper() in await config_csv(TEST_PAYMENT_REST_REFS):
        return True, "test_restaurant"
    return False, "not_allowed"
