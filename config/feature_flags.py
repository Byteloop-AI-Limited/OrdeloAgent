"""
Feature flags stored in the ``ordelo_config`` table.

A flag is on when its ``config_value`` is one of ``true``/``1``/``yes``/``on``
(case-insensitive). A missing key, any other value, or a failed lookup means
off, so code that depends on new SQL can ship before that SQL is run.
Values are cached for 60 seconds so flipping a flag needs no redeploy.

Functions:
  . flag_enabled - async check of one flag (Supabase call runs in a thread)
  . config_csv - async read of a comma-separated ordelo_config value as a set
  . reset_feature_flag_cache - clear the cache (tests, ops)
"""

import asyncio
import time

from loguru import logger

from config.pg_setting import client_ordelo

_FLAG_CACHE_TTL_SECS = 60
_FLAG_CACHE: dict[str, tuple[bool, float]] = {}
_TRUE_VALUES = {"true", "1", "yes", "on"}

# Flags introduced by the ordelo-agg plan (R1a).
ORDER_CREATE_RPC_ENABLED = "ORDER_CREATE_RPC_ENABLED"
PAYMENT_INBOX_ENABLED = "PAYMENT_INBOX_ENABLED"
ENABLE_PAYMENT_TEST_ROUTES = "ENABLE_PAYMENT_TEST_ROUTES"
# Plan D32: restaurants whose orders may use test payments on request.
TEST_PAYMENT_REST_REFS = "TEST_PAYMENT_REST_REFS"

_CSV_CACHE: dict[str, tuple[frozenset[str], float]] = {}


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


def _read_csv(key: str) -> frozenset[str]:
    response = (
        client_ordelo.table("ordelo_config")
        .select("config_value")
        .eq("config_key", key)
        .execute()
    )
    rows = response.data or []
    raw = str(rows[0].get("config_value", "")) if rows else ""
    return frozenset(v.strip().upper() for v in raw.split(",") if v.strip())


async def config_csv(key: str) -> frozenset[str]:
    """Upper-cased values of a comma-separated ``ordelo_config`` key (cached 60 s).

    A missing key or a failed lookup gives an empty set.
    """
    cached = _CSV_CACHE.get(key)
    now = time.monotonic()
    if cached and now - cached[1] < _FLAG_CACHE_TTL_SECS:
        return cached[0]
    try:
        value = await asyncio.to_thread(_read_csv, key)
    except Exception as err:  # noqa: BLE001 - a failed lookup means "empty"
        logger.warning(f"config {key}: lookup failed, treating as empty: {err}")
        value = frozenset()
    _CSV_CACHE[key] = (value, now)
    return value


def reset_feature_flag_cache(key: str | None = None) -> int:
    """Clear one cached flag/list, or all of them. Returns how many were cleared."""
    if key is None:
        count = len(_FLAG_CACHE) + len(_CSV_CACHE)
        _FLAG_CACHE.clear()
        _CSV_CACHE.clear()
        return count
    cleared = (_FLAG_CACHE.pop(key, None) is not None) + (_CSV_CACHE.pop(key, None) is not None)
    return int(cleared)
