"""
Feature flags stored in the ``ordelo_config`` table.

A flag is on when its ``config_value`` is one of ``true``/``1``/``yes``/``on``
(case-insensitive). A missing key, any other value, or a failed lookup means
off.
Values are cached for 60 seconds so flipping a flag needs no redeploy.

Functions:
  . flag_enabled - async check of one flag (Supabase call runs in a thread)
  . config_str - async read of a single ordelo_config string value (None when unset)
  . reset_feature_flag_cache - clear the cache (tests, ops)

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . ordelo_config (table, ordelo_datamodels/core/ordelo_config.sql): reads, named in code (passed to a query helper)
(end of database objects)
"""

import asyncio
import time

from loguru import logger

from config.pg_setting import client_ordelo

_FLAG_CACHE_TTL_SECS = 60
_FLAG_CACHE: dict[str, tuple[bool, float]] = {}
_TRUE_VALUES = {"true", "1", "yes", "on"}

# R3.1 (D35): the R1a-R3 rollout flags are gone. What remains in ordelo_config:
#   {REST}_WEB_ORDERING_PAUSED - emergency stop for new web orders (absent = open)
#   RESTAURANT_MENU_APP_URL    - restaurant-frontend base URL; also the base of web Stripe return links
#                                (absent = payment-service defaults)

_STR_CACHE: dict[str, tuple[str | None, float]] = {}


def _read_flag(key: str) -> bool:
    response = (
        client_ordelo.table("ordelo_config")
        .select("config_value")
        .eq("config_key", key)
        .execute()
    )
    rows = response.data or []
    if not rows:
        return False
    return str(rows[0].get("config_value", "")).strip().lower() in _TRUE_VALUES


async def flag_enabled(key: str) -> bool:
    """Return whether the ``ordelo_config`` flag ``key`` is on (cached 60 s)."""
    cached = _FLAG_CACHE.get(key)
    now = time.monotonic()
    if cached and now - cached[1] < _FLAG_CACHE_TTL_SECS:
        return cached[0]
    try:
        value = await asyncio.to_thread(_read_flag, key)
    except Exception as err:  # noqa: BLE001 - a failed lookup means "off"
        logger.warning(f"feature flag {key}: lookup failed, treating as off: {err}")
        value = False
    _FLAG_CACHE[key] = (value, now)
    return value


def _read_str(key: str) -> str | None:
    response = (
        client_ordelo.table("ordelo_config")
        .select("config_value")
        .eq("config_key", key)
        .execute()
    )
    rows = response.data or []
    value = str(rows[0].get("config_value") or "").strip() if rows else ""
    return value or None


async def config_str(key: str) -> str | None:
    """A single ``ordelo_config`` value (cached 60 s). Missing/blank/failed lookup -> None."""
    cached = _STR_CACHE.get(key)
    now = time.monotonic()
    if cached and now - cached[1] < _FLAG_CACHE_TTL_SECS:
        return cached[0]
    try:
        value = await asyncio.to_thread(_read_str, key)
    except Exception as err:  # noqa: BLE001 - a failed lookup means "not set"
        logger.warning(f"config {key}: lookup failed, treating as unset: {err}")
        value = None
    _STR_CACHE[key] = (value, now)
    return value


def reset_feature_flag_cache(key: str | None = None) -> int:
    """Clear one cached flag/string, or all of them. Returns how many were cleared."""
    if key is None:
        count = len(_FLAG_CACHE) + len(_STR_CACHE)
        _FLAG_CACHE.clear()
        _STR_CACHE.clear()
        return count
    cleared = (
        (_FLAG_CACHE.pop(key, None) is not None)
        + (_STR_CACHE.pop(key, None) is not None)
    )
    return int(cleared)
