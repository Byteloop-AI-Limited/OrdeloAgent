"""Fail-closed web availability, London hours/overnight cutoff and typed pricing.

Existing WhatsApp minimum-spend and opening-hour paths are unchanged. Web uses
fresh restaurant/config reads so a pause takes effect without a deployment.

Database objects (definitions under ordelo_datamodels/; overview: ordelo_datamodels/ordelo-database-guide.md):
  . restaurant_master (table, ordelo_datamodels/core/restaurant_master.sql): reads (SQL)
(end of database objects)
"""

import asyncio
import math
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import requests
from loguru import logger
from config.feature_flags import flag_enabled
from utils_common.order_management.order_service import _call_pricing_service
from .common import RESTAURANTS, WebError, one, postcode_sector, utcnow

UK = ZoneInfo("Europe/London")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def minute(value):
    """Convert integer minutes or HH:MM text to minutes in the range 0..2880.

    Extended times represent overnight service. Reject booleans, invalid minute
    components and out-of-range values with ValueError.
    """
    if isinstance(value, bool):
        raise ValueError("Invalid time")
    if isinstance(value, int):
        result = value
    else:
        hour, minutes = map(int, value.split(":"))
        if hour < 0 or not 0 <= minutes < 60:
            raise ValueError("Invalid time")
        result = hour * 60 + minutes
    if not 0 <= result <= 2880:
        raise ValueError("Invalid time")
    return result


def opening(schedule, at=None, cutoff=15):
    """Return (accepting, next_open_iso) for a London weekly service schedule.

    Include yesterday's overnight span and the next seven days. Intervals use
    minute offsets from local midnight; cutoff removes the end of each window.
    Malformed intervals raise ValueError; no future window returns None.
    """
    local = (at or utcnow()).astimezone(UK)
    intervals = []
    for offset in range(-1, 8):
        day = local.date() + timedelta(days=offset)
        for start, end in (schedule or {}).get(DAYS[day.weekday()], []):
            begin, finish = minute(start), minute(end)
            if not 0 <= begin < 1440 or not begin < finish <= 2880:
                raise ValueError("Invalid service interval")
            base = datetime.combine(day, time(), UK)
            intervals.append(
                (base + timedelta(minutes=begin), base + timedelta(minutes=finish))
            )
    accepting = any(
        start <= local < end - timedelta(minutes=cutoff) for start, end in intervals
    )
    nxt = min(
        (
            start
            for start, end in intervals
            if start > local and end - start > timedelta(minutes=cutoff)
        ),
        default=None,
    )
    return accepting, nxt.isoformat() if nxt else None


async def restaurant(rest_ref):
    """Load fresh restaurant_master data for an allowlisted rest_ref.

    Raise unknown_restaurant for an unregistered ref or a missing database row.
    """
    if rest_ref not in RESTAURANTS:
        raise WebError("unknown_restaurant")
    row = await one("SELECT * FROM restaurant_master WHERE rest_ref=%s", (rest_ref,))
    if not row:
        raise WebError("unknown_restaurant")
    return row


async def available(rest_ref, mode, *, new_order=True):
    """Return fresh restaurant data when its web service window is open.

    For new orders, enforce the emergency pause and a minimum 15-minute cutoff
    for the selected mode. Existing-payment checks skip the pause and cutoff.
    Raise WebError for pause, closure or malformed availability configuration.
    """
    row = await restaurant(rest_ref)
    # R3.1 (D35): every registry restaurant takes web orders. The only switch is
    # the emergency pause, absent by default; it never blocks tracking.
    if new_order and await flag_enabled(f"{rest_ref}_WEB_ORDERING_PAUSED"):
        raise WebError("ordering_paused", 503)
    try:
        cutoff = (
            max(
                15,
                int(
                    row.get(
                        f"{'delivery' if mode == 'delivery' else 'takeaway'}_order_cutoff_minutes"
                    )
                    or 0
                ),
            )
            if new_order
            else 0
        )
        accepting, next_open = opening(row.get("service_hours_json"), cutoff=cutoff)
    except (ValueError, TypeError, KeyError):
        raise WebError("availability_unavailable", 503) from None
    if not accepting:
        raise WebError("restaurant_closed", next_open=next_open)
    return row


async def _google(address):
    """Return Google's first geocode result for a UK address text.

    Run blocking HTTP in a worker with a 12-second timeout. Raise WebError
    invalid_address for ZERO_RESULTS and address_lookup_unavailable (503) for
    provider failures. Coordinates never come from the browser.
    """
    from utils_common.maps_service.address_resolver import API_KEY

    # requests does not emit httpx's INFO log containing address/key query values.
    try:
        response = await asyncio.to_thread(
            requests.get,
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": address, "components": "country:GB", "key": API_KEY},
            timeout=12,
        )
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError):
        raise WebError("address_lookup_unavailable", 503) from None
    if body.get("status") == "ZERO_RESULTS":
        raise WebError("invalid_address")
    if body.get("status") != "OK" or not body.get("results"):
        logger.warning("[web-addr] google status={}", body.get("status"))
        raise WebError("address_lookup_unavailable", 503)
    return body["results"][0]


def _resolved_postcode(result):
    """Return the postal_code Google resolved, or an empty string."""
    return next(
        (
            part["long_name"]
            for part in result.get("address_components", [])
            if "postal_code" in part.get("types", [])
        ),
        "",
    )


def _same_sector(expected_postcode, result):
    """True when Google's resolved postcode is in the expected postcode sector.

    Google often resolves a street number to a neighbouring unit postcode
    (e.g. SP1 3TA typed, SP1 3UE found). The sector (outward code + first
    inward digit) still catches wrong-town results and keeps the point close.
    """
    expected, found = postcode_sector(expected_postcode), postcode_sector(_resolved_postcode(result))
    return bool(expected) and expected == found


async def geocode(address, *, expected_postcode=None):
    """Resolve a UK address or postcode to Google's lat/lng, strictly.

    Reject empty or partial matches and, when supplied, a different postcode
    sector; a unit postcode difference within that sector is allowed. Raise
    WebError for invalid addresses or provider failures. Eligibility uses this
    for the postcode; checkout addresses use locate(), which never rejects.
    """
    result = await _google(address)
    if result.get("partial_match"):
        raise WebError("invalid_address")
    if expected_postcode and not _same_sector(expected_postcode, result):
        raise WebError("invalid_address")
    return result["geometry"]["location"]


_EXACT_TYPES = {"street_address", "premise", "subpremise"}


def _usable_pin(result, postcode):
    """Return (location, precision) for a Google result usable as a rider pin, else None.

    Usable means inside the postcode sector and at least road-level. "exact" is a
    door-level, non-partial match; a road-level or partial match is "street".
    """
    types = set(result.get("types") or [])
    if not _same_sector(postcode, result) or not types & (_EXACT_TYPES | {"route"}):
        return None
    exact = types & _EXACT_TYPES and not result.get("partial_match")
    return result["geometry"]["location"], "exact" if exact else "street"


async def locate(address, postcode, *, street_address=None):
    """Return the locked postcode's centroid and a best-effort rider pin (ADR 0008).

    The centroid comes from the postcode alone, as eligibility quoted it, and
    prices the minimum order. The pin is Google's result for the full address
    when it lands inside the postcode sector ("exact" door-level, "street"
    road-level or partial). If that is unusable (no result, another sector, too
    coarse) retry once with street_address, the same address without premises,
    which can only be "street". Anything still unusable, or a provider error,
    uses the centroid with precision "postcode". The pin never leaves the
    sector. Only a postcode Google can't resolve raises WebError.
    """
    centroid = await geocode(postcode)
    for text, street_only in ((address, False), (street_address, True)):
        if not text or (street_only and text == address):
            continue  # no premises were given, so the first call was already street-only
        try:
            result = await _google(text)
        except WebError as exc:
            if exc.status >= 500:
                break  # provider failure: a second call would likely fail too
            continue  # ZERO_RESULTS: try the street-only text
        usable = _usable_pin(result, postcode)
        if usable:
            location, precision = usable
            return {
                "centroid": centroid,
                "pin": location,
                "precision": "street" if street_only else precision,
            }
    logger.info("[web-addr] pin fallback to postcode centroid")
    return {"centroid": centroid, "pin": centroid, "precision": "postcode"}


async def pricing(row, location, total=0):
    """Return a validated car delivery option for server-resolved coordinates.

    Call the shared pricing service in a worker. Missing car options or negative minimums
    indicate out_of_range; malformed/non-finite prices raise pricing_unavailable.
    Normalize the nonnegative delivery fee from its breakdown or top-level value.
    """
    body = await asyncio.to_thread(
        _call_pricing_service,
        {
            "total_food_value": float(total),
            "restaurant_latitude": row["lat"],
            "restaurant_longitude": row["lon"],
            "customer_latitude": location["lat"],
            "customer_longitude": location["lng"],
            "rest_ref": row["rest_ref"].lower(),
        },
    )
    if not isinstance(body, dict) or not isinstance(body.get("delivery_options"), list):
        raise WebError("pricing_unavailable", 503)
    car = next(
        (
            option
            for option in body["delivery_options"]
            if isinstance(option, dict) and option.get("vehicle_type") == "car"
        ),
        None,
    )
    if car is None:
        raise WebError("out_of_range")
    minimum = car.get("minimum_order_value")
    if (
        isinstance(minimum, bool)
        or not isinstance(minimum, (int, float))
        or not math.isfinite(minimum)
    ):
        raise WebError("pricing_unavailable", 503)
    if minimum < 0:
        raise WebError("out_of_range")
    breakdown = car.get("breakdown") or {}
    fee = breakdown.get("delivery_fee", car.get("delivery_fee", 0))
    if (
        isinstance(fee, bool)
        or not isinstance(fee, (int, float))
        or not math.isfinite(fee)
        or fee < 0
    ):
        raise WebError("pricing_unavailable", 503)
    car = {**car, "delivery_fee": fee}
    return car


async def eligibility(postcode, mode, rest_refs):
    """Build per-restaurant availability and estimated delivery charges.

    Delivery geocodes the postcode once, then quotes each restaurant; collection
    skips geocoding/pricing. Convert per-restaurant WebErrors into public result
    statuses. Initial geocoding failures propagate; town is the first deliverable
    restaurant's registry town, or None.
    """
    location = await geocode(postcode) if mode == "delivery" else {"lat": 0, "lng": 0}
    rows = []
    for rest_ref in rest_refs:
        result = {"rest_ref": rest_ref}
        try:
            row = await available(rest_ref, mode)
            option = await pricing(row, location) if mode == "delivery" else {}
            result.update(
                status="deliverable",
                min_order_value=option.get("minimum_order_value", 0),
                estimated_delivery_fee=option.get("delivery_fee", 0),
            )
        except WebError as exc:
            status = (
                "out_of_range"
                if exc.body["error"] == "out_of_range"
                else "closed"
                if exc.body["error"] == "restaurant_closed"
                else "unavailable"
            )
            result.update(
                status=status,
                reason=exc.body["error"],
                next_open=exc.body.get("next_open"),
            )
        rows.append(result)
    town = next(
        (
            RESTAURANTS[r["rest_ref"]]["town"]
            for r in rows
            if r["status"] == "deliverable"
        ),
        None,
    )
    return {
        "postcode": postcode,
        "lat": location["lat"],
        "lon": location["lng"],
        "town_slug": town,
        "restaurants": rows,
    }
