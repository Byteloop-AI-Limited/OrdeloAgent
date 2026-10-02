"""Fail-closed web availability, London hours/overnight cutoff and typed pricing.

Existing WhatsApp minimum-spend and opening-hour paths are unchanged. Web uses
fresh restaurant/config reads so a pause takes effect without a deployment.
"""
import asyncio
import math
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
import httpx
from config.feature_flags import config_csv, flag_enabled
from utils_common.order_management.order_service import _call_pricing_service
from .common import RESTAURANTS, WebError, one, utcnow

UK = ZoneInfo('Europe/London')
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')

def minute(value):
    if isinstance(value, bool):
        raise ValueError('Invalid time')
    if isinstance(value, int):
        result = value
    else:
        hour, minutes = map(int, value.split(':'))
        if hour < 0 or not 0 <= minutes < 60:
            raise ValueError('Invalid time')
        result = hour * 60 + minutes
    if not 0 <= result <= 2880:
        raise ValueError('Invalid time')
    return result

def opening(schedule, at=None, cutoff=15):
    """Return (accepting, next opening). Includes yesterday's overnight span."""
    local = (at or utcnow()).astimezone(UK)
    intervals = []
    for offset in range(-1, 8):
        day = local.date() + timedelta(days=offset)
        for start, end in (schedule or {}).get(DAYS[day.weekday()], []):
            begin, finish = minute(start), minute(end)
            if not 0 <= begin < 1440 or not begin < finish <= 2880:
                raise ValueError('Invalid service interval')
            base = datetime.combine(day, time(), UK)
            intervals.append((base + timedelta(minutes=begin), base + timedelta(minutes=finish)))
    accepting = any(start <= local < end - timedelta(minutes=cutoff) for start, end in intervals)
    nxt = min((start for start, end in intervals if start > local and end-start > timedelta(minutes=cutoff)), default=None)
    return accepting, nxt.isoformat() if nxt else None

async def restaurant(rest_ref):
    if rest_ref not in RESTAURANTS:
        raise WebError('unknown_restaurant')
    row = await one('SELECT * FROM restaurant_master WHERE rest_ref=%s', (rest_ref,))
    if not row:
        raise WebError('unknown_restaurant')
    return row

async def available(rest_ref, mode, *, new_order=True):
    row = await restaurant(rest_ref)
    if new_order:
        # Empty allowlist means disabled for web, unlike the old notifier pilot.
        refs = await config_csv('WEB_ORDERING_ENABLED_REST_REFS', fail_on_error=True)
        if rest_ref not in refs:
            raise WebError('ordering_paused', 503)
        if not await flag_enabled('PAYMENT_INBOX_ENABLED') or not await flag_enabled('ORDER_CREATE_RPC_ENABLED') or not await flag_enabled('WEB_LATE_PAYMENT_GUARD_ENABLED'):
            raise WebError('ordering_unavailable', 503)
        if await flag_enabled(f'{rest_ref}_WEB_ORDERING_PAUSED') or (
            mode == 'delivery' and await flag_enabled(f'{rest_ref}_WEB_DELIVERY_PAUSED')
        ):
            raise WebError('ordering_paused', 503)
    try:
        cutoff = max(15, int(row.get(f'{"delivery" if mode == "delivery" else "takeaway"}_order_cutoff_minutes') or 0)) if new_order else 0
        accepting, next_open = opening(row.get('service_hours_json'), cutoff=cutoff)
    except (ValueError, TypeError, KeyError):
        raise WebError('availability_unavailable', 503) from None
    if not accepting:
        raise WebError('restaurant_closed', next_open=next_open)
    return row

async def geocode(address):
    # Send the complete manually entered address, not a postcode centroid, for
    # the binding delivery quote. Coordinates never come from the browser.
    from utils_common.maps_service.address_resolver import API_KEY
    async with httpx.AsyncClient(timeout=12) as client:
        try:
            response = await client.get('https://maps.googleapis.com/maps/api/geocode/json', params={
                'address': address, 'components': 'country:GB', 'key': API_KEY,
            })
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise WebError('address_lookup_unavailable', 503) from None
    if body.get('status') == 'ZERO_RESULTS':
        raise WebError('invalid_address')
    if body.get('status') != 'OK' or not body.get('results'):
        raise WebError('address_lookup_unavailable', 503)
    result = body['results'][0]
    if result.get('partial_match'):
        raise WebError('invalid_address')
    return result['geometry']['location']

async def pricing(row, location, total=0):
    body = await asyncio.to_thread(_call_pricing_service, {
        'total_food_value': float(total), 'restaurant_latitude': row['lat'],
        'restaurant_longitude': row['lon'], 'customer_latitude': location['lat'],
        'customer_longitude': location['lng'], 'rest_ref': row['rest_ref'].lower(),
    })
    if not isinstance(body, dict) or not isinstance(body.get('delivery_options'), list):
        raise WebError('pricing_unavailable', 503)
    car = next((option for option in body['delivery_options'] if isinstance(option, dict) and option.get('vehicle_type') == 'car'), None)
    if car is None:
        raise WebError('out_of_range')
    minimum = car.get('minimum_order_value')
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) or not math.isfinite(minimum):
        raise WebError('pricing_unavailable', 503)
    if minimum < 0:
        raise WebError('out_of_range')
    breakdown = car.get('breakdown') or {}
    fee = breakdown.get('delivery_fee', car.get('delivery_fee', 0))
    if isinstance(fee, bool) or not isinstance(fee, (int, float)) or not math.isfinite(fee) or fee < 0:
        raise WebError('pricing_unavailable', 503)
    car = {**car, 'delivery_fee': fee}
    return car

async def eligibility(postcode, mode, rest_refs):
    location = await geocode(postcode) if mode == 'delivery' else {'lat': 0, 'lng': 0}
    rows = []
    for rest_ref in rest_refs:
        result = {'rest_ref': rest_ref}
        try:
            row = await available(rest_ref, mode)
            option = await pricing(row, location) if mode == 'delivery' else {}
            result.update(status='deliverable', min_order_value=option.get('minimum_order_value', 0),
                          estimated_delivery_fee=option.get('delivery_fee', 0))
        except WebError as exc:
            status = 'out_of_range' if exc.body['error'] == 'out_of_range' else 'closed' if exc.body['error'] == 'restaurant_closed' else 'unavailable'
            result.update(status=status, reason=exc.body['error'], next_open=exc.body.get('next_open'))
        rows.append(result)
    town = next((RESTAURANTS[r['rest_ref']]['town'] for r in rows if r['status'] == 'deliverable'), None)
    return {'postcode': postcode, 'lat': location['lat'], 'lon': location['lng'], 'town_slug': town, 'restaurants': rows}
