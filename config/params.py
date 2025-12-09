"""
Restaurant webhook configuration utilities and lookup helpers.
  . Provides async webhook URL construction with dynamic DB lookup
  . WEBHOOK_PATHS maps webhook types to their path suffixes
  . get_restaurant_webhook_url_async fetches base URL from DB on every call (no caching)
  . get_restaurant_admins fetches admin list from restaurant_master
Functions/Classes
  . WEBHOOK_PATHS - Static mapping of webhook type to path suffix
  . get_restaurant_base_url_async - Async DB lookup for restaurant base URL
  . get_restaurant_webhook_url_async - Constructs full webhook URL dynamically
  . get_restaurant_admins - Fetches restaurant admin phone numbers
"""

from loguru import logger


# %% Webhook path mapping - type to path suffix (no base URLs)
WEBHOOK_PATHS = {
    "rider-inflight": "rider-event-hooks/rider-inflight",
    "rider-rest-cc": "rider-event-hooks/on-restaurant-cc",
    "rider-cust-cc": "rider-event-hooks/on-customer-cc",
    "rider-rest-enter": "rider-event-hooks/on-restaurant-enter",
    "rider-cust-enter": "rider-event-hooks/on-customer-enter",
    "delivery-timedout": "rider-event-hooks/delivery-timedout",
    "order-payment-complete": "order-event-hooks/payment-complete/",
    "order-address-update": "order-event-hooks/address-update",
}


# %% get_restaurant_base_url_async
async def get_restaurant_base_url_async(rest_ref: str) -> str:
    """
    Fetch restaurant base URL from database.

    Queries ordelo_config table for {REST_REF}_APP_URL config key.
    No caching - fetches fresh from DB on every call.

    Args:
        rest_ref: Restaurant reference code (e.g., "ELAS", "WREN")

    Returns:
        Base URL string (e.g., "https://api.restaurant.com")

    Raises:
        ValueError: If no config found for the given rest_ref
    """
    from config import client_ordelo

    config_key = rest_ref.upper() + "_APP_URL"
    resp = (
        client_ordelo.table("ordelo_config")
        .select("config_value")
        .eq("config_key", config_key)
        .limit(1)
        .execute()
    )
    data = (
        resp["data"]
        if isinstance(resp, dict) and "data" in resp
        else resp.data
        if hasattr(resp, "data")
        else None
    )
    if not data or len(data) == 0:
        raise ValueError(f"No config found for {config_key} in ordelo_config")

    base_url = data[0]["config_value"]
    logger.debug(f"Fetched base URL for {rest_ref}: {base_url}")
    return base_url


# %% get_restaurant_webhook_url_async
async def get_restaurant_webhook_url_async(rest_ref: str, webhook_type: str) -> str:
    """
    Construct full webhook URL by fetching base URL from DB and appending path.

    This function performs a database lookup on every call (no caching).
    Use this for all outbound webhook calls to restaurant systems.

    Args:
        rest_ref: Restaurant reference code (e.g., "ELAS", "WREN", "ELAB")
        webhook_type: Type of webhook, must be one of:
            - "rider-inflight" - Rider assigned to delivery
            - "rider-rest-cc" - Restaurant confirmation code verified
            - "rider-cust-cc" - Customer confirmation code verified
            - "rider-rest-enter" - Rider entered restaurant zone
            - "rider-cust-enter" - Rider entered customer zone
            - "delivery-timedout" - Delivery timed out
            - "order-payment-complete" - Payment completed
            - "order-address-update" - Customer address updated

    Returns:
        Full webhook URL (e.g., "https://api.restaurant.com/rider-event-hooks/rider-inflight")

    Raises:
        ValueError: If webhook_type is not recognized or rest_ref config not found

    Example:
        url = await get_restaurant_webhook_url_async("ELAS", "rider-inflight")
        # Returns: "https://elas-api.example.com/rider-event-hooks/rider-inflight"
    """
    path = WEBHOOK_PATHS.get(webhook_type.lower())
    if not path:
        valid_types = ", ".join(WEBHOOK_PATHS.keys())
        raise ValueError(
            f"Unknown webhook type: '{webhook_type}'. Valid types: {valid_types}"
        )

    base_url = await get_restaurant_base_url_async(rest_ref)
    full_url = f"{base_url}/{path}"
    logger.debug(f"Constructed webhook URL: {full_url}")
    return full_url


# %%
def get_restaurant_admins(
    rest_ref: str | None = None, rest_id: int | None = None
) -> list[str] | None:
    """Get restaurant admins by rest_ref or rest_id.

    Args:
        rest_ref: Restaurant reference code (e.g., "ELAS")
        rest_id: Restaurant ID

    Returns:
        List of admin identifiers, or None if no restaurant found
    """
    from config import client_ordelo

    if rest_ref is None and rest_id is None:
        raise ValueError("Either rest_ref or rest_id must be provided")

    query = client_ordelo.table("restaurant_master").select("admins")

    if rest_ref is not None:
        query = query.eq("rest_ref", rest_ref.upper())
    else:
        query = query.eq("rest_id", rest_id)

    resp = query.execute()
    data = (
        resp["data"]
        if isinstance(resp, dict) and "data" in resp
        else resp.data
        if hasattr(resp, "data")
        else None
    )

    if not data or len(data) == 0:
        return None

    return data[0]["admins"]


# %%
# Example usage:
# url = await get_restaurant_webhook_url_async("ELAS", "order-address-update")
