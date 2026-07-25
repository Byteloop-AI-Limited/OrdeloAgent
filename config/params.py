"""
Restaurant webhook configuration utilities and lookup helpers.
  . Provides async webhook URL construction with dynamic DB lookup
  . WEBHOOK_PATHS maps webhook types to their path templates (with {rest_ref} placeholder)
  . get_restaurant_webhook_url_async fetches base URL from DB (now cached)
  . _REST_REF_ALIAS_MAP allows multiple rest_refs to share a canonical rest_ref for DB lookups
  . ONBOARDED_REST_REFS tracks canonical onboarded restaurant references
  . is_onboarded_rest_ref checks onboarding status after alias resolution
Functions/Classes
  . WEBHOOK_PATHS - Static mapping of webhook type to path template with {rest_ref}
  . _REST_REF_ALIAS_MAP - Alias map: alias rest_ref -> canonical rest_ref for DB lookups
  . ONBOARDED_REST_REFS - Canonical onboarded restaurant references
  . _resolve_rest_ref - Resolves a rest_ref to its canonical form via _REST_REF_ALIAS_MAP
  . is_onboarded_rest_ref - Checks whether a rest_ref is onboarded via canonical resolution
  . get_restaurant_base_url_async - Async DB lookup for restaurant base URL (cached, alias-aware)
  . get_restaurant_webhook_url_async - Constructs full webhook URL dynamically, substituting rest_ref
"""

import asyncio
import time
from typing import Literal, Optional

from loguru import logger

_BASE_URL_CACHE_TTL_SECS = 60 * 60  # 1 hour
_BASE_URL_CACHE: dict[str, tuple[str, float]] = {}
_OVERWATCH_LIST_CACHE_TTL_SECS = 60 * 60  # 1 hour
_OVERWATCH_LIST_CACHE: tuple[list[str], float] | None = None

_APP_URL_CACHE_TTL_SECS = 60 * 60  # 1 hour
_APP_URL_CACHE: dict[str, tuple[str, float]] = {}

DashboardRole = Literal["sys_admin", "rest_admin", "rider"]

_ROLE_TO_APP_URL_CONFIG_KEY: dict[str, str] = {
    "sys_admin":  "RESTAURANT_MENU_APP_URL",
    "rest_admin": "RESTAURANT_MENU_APP_URL",
    "rider":      "RESTAURANT_MENU_APP_URL",
}

# Alias map: rest_refs that share config with another rest_ref.
# Key = alias rest_ref, Value = canonical rest_ref used for DB lookups.
_REST_REF_ALIAS_MAP: dict[str, str] = {
    "CHKS": "ELAS",
}

ONBOARDED_REST_REFS: set[str] = {
    "ELAS",
    "SFCS",
}


def _resolve_rest_ref(rest_ref: str) -> str:
    """Resolve rest_ref alias to canonical rest_ref for DB lookups."""
    upper = rest_ref.upper()
    return _REST_REF_ALIAS_MAP.get(upper, upper)


def is_onboarded_rest_ref(rest_ref: str) -> bool:
    """Return whether a restaurant reference is onboarded after alias resolution."""
    return _resolve_rest_ref(rest_ref) in ONBOARDED_REST_REFS


# %% Webhook path mapping - type to path template with {rest_ref} placeholder
# Note: {rest_ref} comes AFTER the router prefix since routers are mounted with prefix in FastAPI
WEBHOOK_PATHS = {
    "rider-inflight": "rider-event-hooks/{rest_ref}/rider-inflight",
    "rider-rest-cc": "rider-event-hooks/{rest_ref}/on-restaurant-cc",
    "rider-cust-cc": "rider-event-hooks/{rest_ref}/on-customer-cc",
    "rider-rest-enter": "rider-event-hooks/{rest_ref}/on-restaurant-enter",
    "rider-cust-enter": "rider-event-hooks/{rest_ref}/on-customer-enter",
    "delivery-timedout": "rider-event-hooks/{rest_ref}/delivery-timedout",
    "order-payment-complete": "order-event-hooks/{rest_ref}/payment-complete",
    "order-pickup-time-updated": "order-event-hooks/{rest_ref}/takeaway-pickup-time-updated",
    "order-takeaway-ready": "order-event-hooks/{rest_ref}/takeaway-ready",
    "order-address-update": "order-event-hooks/{rest_ref}/address-update",
    "get-active-thread": "thread-hooks/get-active-thread",  # Already has rest_ref in existing path
}


# %% get_restaurant_base_url_async
async def get_restaurant_base_url_async(rest_ref: str) -> str:
    """
    Fetch restaurant base URL from database with in-memory caching.

    Queries ordelo_config table for {REST_REF}_APP_URL config key.
    Results are cached for 5 minutes to avoid repeated DB lookups.

    Args:
        rest_ref: Restaurant reference code (e.g., "ELAS", "WREN")

    Returns:
        Base URL string (e.g., "https://api.restaurant.com")

    Raises:
        ValueError: If no config found for the given rest_ref
    """
    from config import client_ordelo

    rest_ref_upper = _resolve_rest_ref(rest_ref)
    cache_key = rest_ref_upper
    now = time.monotonic()

    cached = _BASE_URL_CACHE.get(cache_key)
    if cached:
        cached_value, expires_at = cached
        if expires_at > now:
            logger.debug(f"Using cached base URL for {rest_ref_upper}: {cached_value}")
            return cached_value
        _BASE_URL_CACHE.pop(cache_key, None)

    config_key = rest_ref_upper + "_APP_URL"
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
    _BASE_URL_CACHE[cache_key] = (base_url, now + _BASE_URL_CACHE_TTL_SECS)
    logger.debug(f"Fetched base URL for {rest_ref_upper}: {base_url}")
    return base_url


# %% reset_restaurant_base_url_cache
def reset_restaurant_base_url_cache(rest_ref: str | None = None) -> int:
    """Reset the in-memory base URL cache used by get_restaurant_base_url_async.

    Args:
        rest_ref: Optional restaurant reference. If provided, clears only that
            entry (case-insensitive). If None, clears the entire cache.

    Returns:
        Number of cache entries removed.
    """
    if rest_ref is None:
        removed = len(_BASE_URL_CACHE)
        _BASE_URL_CACHE.clear()
        logger.debug(f"Cleared base URL cache ({removed} entries)")
        return removed

    cache_key = rest_ref.upper()
    existed = cache_key in _BASE_URL_CACHE
    _BASE_URL_CACHE.pop(cache_key, None)
    if existed:
        logger.debug(f"Cleared base URL cache for {cache_key}")
        return 1
    logger.debug(f"No base URL cache entry for {cache_key} to clear")
    return 0


# %% get_overwatch_list
def get_overwatch_list() -> list[str]:
    """Get overwatch list from ordelo_config with in-memory caching."""
    from config import client_ordelo

    global _OVERWATCH_LIST_CACHE
    now = time.monotonic()
    if _OVERWATCH_LIST_CACHE:
        cached_value, expires_at = _OVERWATCH_LIST_CACHE
        if expires_at > now:
            logger.debug("Using cached overwatch list")
            return cached_value
        _OVERWATCH_LIST_CACHE = None

    resp = (
        client_ordelo.table("ordelo_config")
        .select("config_value")
        .eq("config_key", "overwatch_list")
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
        raise ValueError("No config found for overwatch_list in ordelo_config")

    raw_value = data[0]["config_value"] or ""
    parsed = [item.strip() for item in raw_value.split(",") if item.strip()]
    _OVERWATCH_LIST_CACHE = (parsed, now + _OVERWATCH_LIST_CACHE_TTL_SECS)
    return parsed


# %% reset_overwatch_list_cache
def reset_overwatch_list_cache() -> int:
    """Reset the in-memory overwatch list cache used by get_overwatch_list."""
    global _OVERWATCH_LIST_CACHE
    existed = _OVERWATCH_LIST_CACHE is not None
    _OVERWATCH_LIST_CACHE = None
    if existed:
        logger.debug("Cleared overwatch list cache")
        return 1
    logger.debug("No overwatch list cache entry to clear")
    return 0


# %% get_dashboard_app_url_async
async def get_dashboard_app_url_async(role: DashboardRole) -> str:
    """Return the dashboard base URL for a given role, cached for 1 hour."""
    from config import client_ordelo

    config_key = _ROLE_TO_APP_URL_CONFIG_KEY[role]
    now = time.monotonic()

    cached = _APP_URL_CACHE.get(config_key)
    if cached:
        value, expires_at = cached
        if expires_at > now:
            return value
        _APP_URL_CACHE.pop(config_key, None)

    resp = await asyncio.to_thread(
        lambda: client_ordelo.table("ordelo_config")
        .select("config_value")
        .eq("config_key", config_key)
        .single()
        .execute()
    )
    value = resp.data["config_value"]
    _APP_URL_CACHE[config_key] = (value, now + _APP_URL_CACHE_TTL_SECS)
    logger.debug(f"Fetched app URL for role={role} config_key={config_key}: {value}")
    return value


# %% reset_app_url_cache
def reset_app_url_cache(role: Optional[DashboardRole] = None) -> int:
    """Reset the in-memory app URL cache. role=None clears all entries."""
    if role is None:
        removed = len(_APP_URL_CACHE)
        _APP_URL_CACHE.clear()
        logger.debug(f"Cleared app URL cache ({removed} entries)")
        return removed

    config_key = _ROLE_TO_APP_URL_CONFIG_KEY[role]
    existed = config_key in _APP_URL_CACHE
    _APP_URL_CACHE.pop(config_key, None)
    if existed:
        logger.debug(f"Cleared app URL cache for role={role} config_key={config_key}")
        return 1
    logger.debug(f"No app URL cache entry for role={role} to clear")
    return 0


# %% get_wa_logger
async def get_wa_logger():
    from config import _async_wa_client, WALogger

    overwatch_list = get_overwatch_list()
    return WALogger(wa=_async_wa_client, overwatch_list=overwatch_list)


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
            - "order-takeaway-ready" - Takeaway order marked ready by admin
            - "order-address-update" - Customer address updated

    Returns:
        Full webhook URL (e.g., "https://api.restaurant.com/rider-event-hooks/rider-inflight")

    Raises:
        ValueError: If webhook_type is not recognized or rest_ref config not found

    Example:
        url = await get_restaurant_webhook_url_async("ELAS", "rider-inflight")
        # Returns: "https://elas-api.example.com/rider-event-hooks/rider-inflight"
    """
    path_template = WEBHOOK_PATHS.get(webhook_type.lower())
    if not path_template:
        valid_types = ", ".join(WEBHOOK_PATHS.keys())
        raise ValueError(
            f"Unknown webhook type: '{webhook_type}'. Valid types: {valid_types}"
        )

    # Substitute rest_ref into path template
    resolved_ref = _resolve_rest_ref(rest_ref)
    path = path_template.format(rest_ref=resolved_ref)

    base_url = await get_restaurant_base_url_async(rest_ref)
    full_url = f"{base_url}/{path}"
    return full_url


# %%
# Example usage:
# url = await get_restaurant_webhook_url_async("ELAS", "order-address-update")
