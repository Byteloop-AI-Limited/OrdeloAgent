"""
Pydantic model for restaurant_master table
    . Defines fields and types to match the restaurant_master DDL
    . Handles nullability with Optional
    . Depends on pydantic, datetime, and config.client_ordelo
    . Models the restaurant_master table structure
    . Provides from_rest_ref to instantiate from DB (cached, alias-aware)
    . Provides get_admins to return admins from cached object
  Functions/Classes:
    . RestaurantMaster
        . from_rest_ref
        . get_admins
    . reset_restaurant_master_cache
"""

# %%
import datetime
import time
from typing import Optional
from loguru import logger
from pydantic import BaseModel

_RESTAURANT_MASTER_CACHE_TTL_SECS = 60 * 60  # 1 hour
_RESTAURANT_MASTER_CACHE: dict[str, tuple["RestaurantMaster", float]] = {}


class RestaurantMaster(BaseModel):
    rest_ref: str  # character varying, NOT NULL
    rest_id: Optional[str] = None  # character varying, NULL
    rest_name: str  # text, NOT NULL
    rest_email: Optional[str] = None  # text, NULL
    admins: Optional[list[str]] = None  # text[], NULL
    house_number: str  # text, NOT NULL
    building_name: Optional[str] = None  # text, NULL
    street_name: str  # text, NOT NULL
    city: str  # text, NOT NULL
    postcode: str  # text, NOT NULL
    lat: float  # double precision, NOT NULL
    lon: float  # double precision, NOT NULL
    dt: datetime.date  # date, NOT NULL
    dtts: datetime.datetime  # timestamp with time zone, NOT NULL
    collection_commission: Optional[float] = None  # e.g. 0.04 for 4%

    @classmethod
    def from_rest_ref(cls, rest_ref: str):
        from config import client_ordelo
        from config.params import _resolve_rest_ref

        canonical = _resolve_rest_ref(rest_ref)
        now = time.monotonic()

        cached = _RESTAURANT_MASTER_CACHE.get(canonical)
        if cached:
            cached_value, expires_at = cached
            if expires_at > now:
                logger.debug(f"Using cached RestaurantMaster for {canonical}")
                return cached_value
            _RESTAURANT_MASTER_CACHE.pop(canonical, None)

        resp = (
            client_ordelo.table("restaurant_master")
            .select("*")
            .eq("rest_ref", canonical)
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
            raise ValueError(f"No restaurant found with rest_ref={rest_ref}")

        row = data[0]
        instance = cls(**row)
        _RESTAURANT_MASTER_CACHE[canonical] = (instance, now + _RESTAURANT_MASTER_CACHE_TTL_SECS)
        logger.debug(f"Fetched and cached RestaurantMaster for {canonical}")
        return instance

    def get_admins(self) -> list[str] | None:
        """Return admins from the cached RestaurantMaster object."""
        return self.admins


# %%
def reset_restaurant_master_cache(rest_ref: str | None = None) -> int:
    """Reset the in-memory RestaurantMaster cache.

    Args:
        rest_ref: Optional restaurant reference. If provided, clears only that
            entry (case-insensitive, alias-aware). If None, clears the entire cache.

    Returns:
        Number of cache entries removed.
    """
    from config.params import _resolve_rest_ref

    if rest_ref is None:
        removed = len(_RESTAURANT_MASTER_CACHE)
        _RESTAURANT_MASTER_CACHE.clear()
        logger.debug(f"Cleared RestaurantMaster cache ({removed} entries)")
        return removed

    cache_key = _resolve_rest_ref(rest_ref)
    existed = cache_key in _RESTAURANT_MASTER_CACHE
    _RESTAURANT_MASTER_CACHE.pop(cache_key, None)
    if existed:
        logger.debug(f"Cleared RestaurantMaster cache for {cache_key}")
        return 1
    logger.debug(f"No RestaurantMaster cache entry for {cache_key} to clear")
    return 0


# %%
# RestaurantMaster.from_rest_ref("wren")
# from config import client_ordelo
# client_ordelo.table("restaurant_master").select("*").eq("rest_ref", "WREN").execute()
