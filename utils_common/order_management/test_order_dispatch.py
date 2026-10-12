"""Resolve TEST3100 delivery audiences without changing payment snapshots.

Order markers are looked up by order number. Overwatch is an operational rider
audience, never a condition on the ordering customer. Reads fail closed and
membership is refreshed for each send rather than using the alerts cache.
"""

import asyncio

from config import client_ordelo, logger


async def order_has_test_item(order_number: str) -> bool:
    """Return the scoped database classification; unknown orders are errors."""
    response = await asyncio.to_thread(
        lambda: client_ordelo.rpc(
            "order_has_test_item", {"p_order_number": order_number}
        ).execute()
    )
    if not isinstance(response.data, bool):
        raise ValueError(f"Dispatch order classification unavailable: {order_number}")
    return response.data


async def read_overwatch_riders() -> frozenset[str]:
    """Read current trimmed membership. Missing/empty membership allows nobody."""
    response = await asyncio.to_thread(
        lambda: client_ordelo.table("ordelo_config").select("config_value")
        .eq("config_key", "overwatch_list").limit(1).execute()
    )
    rows = response.data or []
    raw = (rows[0].get("config_value") or "") if rows else ""
    return frozenset(number.strip() for number in raw.split(",") if number.strip())


async def rider_dispatch_allowed(order_number: str, rider_id: str) -> bool:
    """Fresh send-time check; normal orders do not depend on overwatch reads."""
    try:
        if not await order_has_test_item(order_number):
            return True
        allowed = rider_id in await read_overwatch_riders()
        if not allowed:
            logger.info("dispatch suppressed order={} reason=test_order_non_overwatch_rider", order_number)
        return allowed
    except Exception:
        # Do not log an upstream exception body: it can contain customer data.
        logger.error("dispatch suppressed order={} reason=classification_unavailable", order_number)
        return False
