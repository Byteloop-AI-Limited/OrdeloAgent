# `get_restaurant_webhook_url_async` Usage Guide

## Overview

`get_restaurant_webhook_url_async` is an async function that constructs full webhook URLs by dynamically fetching the restaurant's base URL from the database on every call. This ensures webhook URLs always reflect the current configuration without requiring application restarts.

## Location

```python
from config import get_restaurant_webhook_url_async
# or
from config.params import get_restaurant_webhook_url_async
```

## Function Signature

```python
async def get_restaurant_webhook_url_async(rest_ref: str, webhook_type: str) -> str:
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `rest_ref` | `str` | Restaurant reference code (e.g., `"ELAS"`, `"WREN"`, `"ELAB"`) |
| `webhook_type` | `str` | Type of webhook (see valid types below) |

### Valid Webhook Types

| Type | Path | Description |
|------|------|-------------|
| `rider-inflight` | `rider-event-hooks/rider-inflight` | Rider assigned to delivery |
| `rider-rest-cc` | `rider-event-hooks/on-restaurant-cc` | Restaurant confirmation code verified |
| `rider-cust-cc` | `rider-event-hooks/on-customer-cc` | Customer confirmation code verified |
| `rider-rest-enter` | `rider-event-hooks/on-restaurant-enter` | Rider entered restaurant zone |
| `rider-cust-enter` | `rider-event-hooks/on-customer-enter` | Rider entered customer zone |
| `delivery-timedout` | `rider-event-hooks/delivery-timedout` | Delivery timed out |
| `order-payment-complete` | `order-event-hooks/payment-complete/` | Payment completed |
| `order-address-update` | `order-event-hooks/address-update` | Customer address updated |

### Returns

- `str`: Full webhook URL (e.g., `"https://api.restaurant.com/rider-event-hooks/rider-inflight"`)

### Raises

- `ValueError`: If `webhook_type` is not recognized
- `ValueError`: If no config found for the given `rest_ref` in `ordelo_config` table

## Database Configuration

The function reads from the `ordelo_config` table:

| config_key | config_value |
|------------|--------------|
| `ELAS_APP_URL` | `https://elas-api.example.com` |
| `WREN_APP_URL` | `https://wren-api.example.com` |
| `ELAB_APP_URL` | `https://elab-api.example.com` |
| `ORDELO_APP_URL` | `https://ordelo-api.example.com` |

## Usage Examples

### Basic Usage

```python
from config import get_restaurant_webhook_url_async
import httpx

async def notify_rider_inflight(order_number: str, payload: dict):
    rest_ref = order_number.split("-")[0]  # Extract rest_ref from order number
    webhook_url = await get_restaurant_webhook_url_async(rest_ref, "rider-inflight")
    
    async with httpx.AsyncClient() as client:
        response = await client.post(webhook_url, json=payload)
```

### With Path Parameters

```python
async def post_rider_event_customer_cc(order_number: str, customer_id: int):
    rest_ref = order_number.split("-")[0]
    webhook_url = await get_restaurant_webhook_url_async(rest_ref, "rider-cust-cc")
    
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{webhook_url}/{order_number}/{customer_id}",
            json={},
        )
```

### Error Handling

```python
async def safe_webhook_call(rest_ref: str, webhook_type: str, payload: dict):
    try:
        webhook_url = await get_restaurant_webhook_url_async(rest_ref, webhook_type)
    except ValueError as e:
        logger.error(f"Failed to get webhook URL: {e}")
        return None
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Webhook call failed: {e}")
            return None
```

## Related Functions

### `get_restaurant_base_url_async`

Fetches only the base URL without constructing the full webhook path:

```python
from config.params import get_restaurant_base_url_async

base_url = await get_restaurant_base_url_async("ELAS")
# Returns: "https://elas-api.example.com"
```

### `WEBHOOK_PATHS`

Static dictionary mapping webhook types to their path suffixes:

```python
from config.params import WEBHOOK_PATHS

print(WEBHOOK_PATHS)
# {
#     "rider-inflight": "rider-event-hooks/rider-inflight",
#     "rider-rest-cc": "rider-event-hooks/on-restaurant-cc",
#     ...
# }
```

## Migration Notes

This function replaces the deprecated `get_webhook_url` (sync) function. Key differences:

| Old (Deprecated) | New |
|------------------|-----|
| `get_webhook_url(rest_ref, type)` | `await get_restaurant_webhook_url_async(rest_ref, webhook_type)` |
| Cached base URLs at startup | Fresh DB lookup every call |
| Required `RESTAURANT_CONFIG` dict | Uses `WEBHOOK_PATHS` + DB lookup |
| Sync function | Async function |

### Migration Example

```python
# Before (deprecated)
url = get_webhook_url(rest_ref, "rider-inflight")

# After
url = await get_restaurant_webhook_url_async(rest_ref, "rider-inflight")
```

## Performance Considerations

- **No caching**: Each call queries the database
- **Use case**: Ideal when configuration changes need immediate effect
- **Trade-off**: Slightly higher latency per call vs. cached approach

## Files Using This Function

| File | Usage |
|------|-------|
| `ordelo/agent_app_handlers.py` | Customer/Restaurant CC webhooks |
| `watomation/routers/delivery_hooks.py` | Rider inflight, delivery timeout |
| `watomation/routers/location_hooks.py` | Zone enter events |
| `watomation/routers/order_hooks.py` | Address update webhook |
| `watomation/routers/payment_hooks.py` | Payment complete webhook |
| `watomation/fapp_ordelo_agent.py` | Diagnostic endpoint |
