# Ordelo Payment and Order Flow

**Version:** 1.0
**Last Updated:** 2026-02-14

This document covers the order creation and payment lifecycle within OrdeloAgent, from pre-order validation through payment completion and routing to either delivery or takeaway initialization. For delivery-specific phases, see `docs/delivery_process.md`. For takeaway-specific phases, see `docs/takeaway_flow.md`.

---

## Table of Contents

1. [Overview](#overview)
2. [Pre-Order Validation](#pre-order-validation)
   - [Minimum Order Value by Coordinates](#minimum-order-value-by-coordinates)
   - [Minimum Order Value by Postcode](#minimum-order-value-by-postcode)
   - [Postcode Validator](#postcode-validator)
3. [Order Creation](#order-creation)
4. [Payment Paths](#payment-paths)
   - [Stripe Payment (Delivery)](#stripe-payment-delivery)
   - [Stripe Payment (Takeaway)](#stripe-payment-takeaway)
   - [Pay-at-Restaurant (Takeaway Only)](#pay-at-restaurant-takeaway-only)
5. [Payment Completion Handler](#payment-completion-handler)
6. [Address Capture](#address-capture)
7. [Supporting Operations](#supporting-operations)
8. [Status Transitions](#status-transitions)
9. [Webhook Endpoints](#webhook-endpoints)

---

## Overview

The order and payment flow begins when a customer places an order through the restaurant frontend. The system validates the order, creates database records, generates a payment URL, and upon payment completion routes the order to either the delivery or takeaway initialization path.

### High-Level Flow

```
Pre-Order Validation (min order value check)
  → POST /create-order/{rest_ref} (order + order_items created in DB)
  → Payment URL returned to frontend
  → Customer completes payment (Stripe) or pays at restaurant
  → POST /payment-complete (Stripe webhook) or POST /pay-at-restaurant/{rest_ref}
  → Routes to init_delivery() or init_takeaway() based on food_order.action
  → DB triggers fire restaurant confirmation webhooks
```

---

## Pre-Order Validation

Before creating an order, the frontend can check whether the customer's location meets the minimum order value requirements.

### Minimum Order Value by Coordinates

**Endpoint:** `GET /order-hooks/get-min-order-value`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `customer_latitude` | float | Yes | Customer latitude |
| `customer_longitude` | float | Yes | Customer longitude |
| `restaurant_latitude` | float | No | Restaurant latitude (must pair with longitude) |
| `restaurant_longitude` | float | No | Restaurant longitude (must pair with latitude) |
| `rest_ref` | str | No | Restaurant reference (used when lat/lon not provided) |

Either `restaurant_latitude`/`restaurant_longitude` or `rest_ref` must be provided. If `rest_ref` is given without explicit coordinates, the restaurant's coordinates are resolved from `restaurant_master` via `RestaurantMaster.from_rest_ref()`.

The endpoint calls the pricing microservice (`_call_pricing_service`) and returns the minimum order value for the `car` vehicle type. Returns `-1` if the customer is outside the delivery range.

**Response:**
```json
{
  "status": "ok",
  "min_order_value": 10.0,
  "source": "service"
}
```

**Source:** `watomation/routers/order_hooks.py:52-124` (`get_min_order_value`)

### Minimum Order Value by Postcode

**Endpoint:** `GET /order-hooks/get-min-order-value-by-postcode`

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `customer_postcode` | str | Yes | Customer UK postcode |
| `restaurant_postcode` | str | No | Restaurant UK postcode (when `rest_ref` absent) |
| `rest_ref` | str | No | Restaurant reference (preferred over postcode) |

Resolves postcodes to coordinates via `address_resolver.get_address_from_postcode()` before delegating to the same pricing service lookup. Either `restaurant_postcode` or `rest_ref` must be provided.

**Source:** `watomation/routers/order_hooks.py:127-199` (`get_min_order_value_by_postcode`)

### Postcode Validator

**Endpoint:** `GET /order-hooks/postcode-validator/{postcode}`

Validates a UK postcode using the address resolver and returns the resolved address data.

**Source:** `watomation/routers/order_hooks.py:304-317` (`validate_postcode`)

---

## Order Creation

**Endpoint:** `POST /order-hooks/create-order/{rest_ref}`

**Request Model:** `CreateOrderRequest`

```json
{
  "recipient": "447448440754",
  "thread_id": "1239876lkjsd",
  "order_items": [
    {
      "order_id": "placeholder",
      "product_name": "Chicken Burger",
      "sku": "chicken_burger",
      "quantity": 1,
      "price": 20
    }
  ],
  "order_type": "delivery",
  "notes": "No onions"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `recipient` | str | Customer phone number |
| `thread_id` | str | WhatsApp thread ID |
| `order_items` | List[OrderItem] | Items with sku, quantity, price, product_name |
| `order_type` | str | `"delivery"` or `"takeaway"` |
| `notes` | str? | Optional order notes |

### Order Creation Logic

**Source:** `utils_common/order_management/order_service.py:174-306` (`create_order_with_items`)

1. **Sequence number**: Calls `get_next_daily_seq` RPC to get the daily sequence counter
2. **Order reference**: Generates a 4-character hashed reference from the last 4 digits of the recipient phone number, a salt, and the order date via `create_order_reference()`
3. **Order ID**: `{order_reference}-{seq_number}` (e.g., `KDDV-21`)
4. **Order number**: `{REST_REF}-{order_reference}-{seq_number}` (e.g., `ELAS-KDDV-21`)
5. **food_order INSERT**: Inserts into `food_order` table with `payment_status = 'requires_payment'` and `action` set to `order_type`
6. **order_item INSERT**: Inserts all order items linked to the order_id. If this fails, the food_order record is rolled back (deleted)
7. **Final order value**: After insert, `FoodOrder.from_order_id()` is called, which triggers `update_final_order_value_in_db()` for delivery orders (calls pricing microservice to calculate fees)

### Payment URL Generation

After the order is created, a payment URL is generated based on the order type:

| Order Type | Function | Payment Mode | Fees Included |
|------------|----------|--------------|---------------|
| `delivery` | `generate_payment_intent_url()` | Manual capture (`manual_mode_capture: true`) | Service charge, delivery fee, small order fee |
| `takeaway` | `generate_automatic_payment_url()` | Automatic capture (`manual_mode_capture: false`) | Product items only (no delivery fees) |

Both functions POST to the Stripe payment service at the `payment_uri` derived from `FoodOrder.payment_uri`, which constructs the URL as:
```
{stripe_url}/threads/{thread_id}/orders/{order_id}/payment-url
```

Overwatch customers (configured test accounts) use `stripe_url_test` instead.

**Response:**
```json
{
  "status": "success",
  "order_id": "KDDV-21",
  "recipient": "447448440754",
  "thread_id": "1239876lkjsd",
  "order_number": "ELAS-KDDV-21",
  "payment_intent_url": "https://checkout.stripe.com/...",
  "service_charge": 1.50,
  "delivery_fee": 3.00,
  "small_order_fee": 0,
  "notes": "No onions"
}
```

**Source:** `watomation/routers/order_hooks.py:212-300` (`create_order`)

---

## Payment Paths

### Stripe Payment (Delivery)

```
Customer → Stripe Checkout (manual capture) → Stripe webhook
  → POST /payment-hooks/payment-complete
  → food_order.payment_status = 'requires_capture'
  → handle_payment_complete() → restaurant webhook notification
  → init_delivery_summary() → init_delivery RPC
  → delivery_summary created → DB triggers → restaurant confirmation flow
```

Payment is captured later during the inflight phase (when a rider is assigned) via `capture_payment()`.

### Stripe Payment (Takeaway)

```
Customer → Stripe Checkout (automatic capture) → Stripe webhook
  → POST /payment-hooks/payment-complete
  → food_order.payment_status = 'requires_capture'
  → handle_payment_complete() → restaurant webhook notification
  → init_takeaway_summary() → init_takeaway RPC
  → takeaway_summary created → DB triggers → restaurant confirmation flow
```

For takeaway, Stripe captures the payment automatically (no manual capture needed later).

### Pay-at-Restaurant (Takeaway Only)

```
Restaurant frontend → POST /payment-hooks/pay-at-restaurant/{rest_ref}
  → Validates order_type == 'takeaway'
  → food_order.payment_status = 'pay_at_rest'
  → handle_payment_complete() → restaurant webhook notification
  → init_takeaway_summary() → init_takeaway RPC
  → takeaway_summary created → DB triggers → restaurant confirmation flow
```

Pay-at-restaurant is restricted to takeaway orders only. The endpoint returns HTTP 400 if `order_type != "takeaway"`.

**Source:** `watomation/routers/payment_hooks.py:171-215` (`pay_at_restaurant`)

---

## Payment Completion Handler

**Endpoint:** `POST /payment-hooks/payment-complete`

**Trigger:** Stripe success webhook

**Source:** `watomation/routers/payment_hooks.py:96-135` (`payment_complete_path`)

### Processing Steps

1. **Extract order_id** from Stripe webhook payload at `data.object.metadata.orderID`
2. **Update payment status**: Sets `food_order.payment_status` to `requires_capture`
3. **Notify restaurant**: Schedules `handle_payment_complete()` as a background task, which POSTs the food order data to the restaurant's `order-payment-complete` webhook at:
   ```
   {restaurant_webhook_url}/order-payment-complete/{recipient}/{thread_id}
   ```
4. **Route by action**: Based on `food_order.action`:
   - `"delivery"` → schedules `init_delivery_summary()` background task → calls `init_delivery` RPC
   - `"takeaway"` → schedules `init_takeaway_summary()` background task → calls `init_takeaway` RPC
   - Unknown action → logs warning, skips summary initialization

### init_delivery_summary vs init_takeaway_summary

| Function | RPC Called | Creates | Source |
|----------|-----------|---------|--------|
| `init_delivery_summary()` | `init_delivery(p_cust_id, p_order_number)` | `delivery_summary` record | `watomation/routers/payment_hooks.py:80-90` |
| `init_takeaway_summary()` | `init_takeaway(p_cust_id, p_order_number)` | `takeaway_summary` record | `watomation/routers/takeaway_hooks.py:132-142` |

Both are synchronous functions run as background tasks via `BackgroundTasks.add_task()`.

---

## Address Capture

**Endpoint:** `POST /order-hooks/capture-address`

**Request Model:** `CaptureAddressRequest`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `recipient` | str | Yes | Customer phone number |
| `rest_ref` | str | Yes | Restaurant reference code |
| `house_number` | str | No | House number |
| `building_name` | str | No | Building name |
| `street_name` | str | No | Street name |
| `locality` | str | No | Locality |
| `city` | str | Yes | City |
| `county` | str | No | County |
| `postcode` | str | Yes | UK postcode |
| `country` | str | No | Country |
| `latitude` | float | Yes | Customer latitude |
| `longitude` | float | Yes | Customer longitude |

### Processing Steps

1. Constructs a `CustomerMaster` record from the request fields (uses `recipient` as `cust_id` and `cust_name`)
2. Upserts into `customer_master` table via Supabase REST
3. Notifies the restaurant service by POSTing to the `order-address-update` webhook:
   ```
   {restaurant_webhook_url}/order-address-update/{recipient}
   ```

**Source:** `watomation/routers/order_hooks.py:321-382` (`capture_address`)

---

## Supporting Operations

### Active Thread Lookup

**Endpoint:** `GET /order-hooks/get-active-thread/{rest_ref}/{recipient}`

Proxies the request to the restaurant's `get-active-thread` webhook. Returns the upstream response content and status directly.

**Source:** `watomation/routers/order_hooks.py:413-440` (`get_active_thread`)

### Stale Thread Termination

**Endpoint:** `POST /order-hooks/terminate-stale-active-threads`

Triggered by a database job to notify the restaurant system to clean up stale threads. POSTs to the restaurant's `terminate-stale-active-threads` webhook. Currently hardcoded to `rest_ref = "ELAS"`.

**Source:** `watomation/routers/order_hooks.py:385-410` (`terminate_stale_active_threads`)

### Payment Complete Test

**Endpoint:** `POST /payment-hooks/payment-complete-test/{order_number}`

A test endpoint that directly triggers `init_delivery_summary` or `init_takeaway_summary` without requiring a Stripe webhook. Accepts `recipient` and `action` query parameters.

**Source:** `watomation/routers/payment_hooks.py:141-154` (`payment_complete_test_path`)

---

## Status Transitions

### food_order.payment_status

```
requires_payment (initial, set at order creation)
  ├── requires_capture (Stripe payment complete → manual capture pending)
  └── pay_at_rest (pay-at-restaurant path → no Stripe involved)
```

### Complete Order-to-Initialization Journey

```
1. POST /create-order/{rest_ref}
   └── food_order created
       ├── payment_status = 'requires_payment'
       ├── action = 'delivery' | 'takeaway'
       └── Payment URL returned to frontend

2a. Stripe Payment Path
    └── Customer completes Stripe checkout
        └── POST /payment-complete (Stripe webhook)
            ├── payment_status → 'requires_capture'
            ├── handle_payment_complete() → restaurant notified
            └── food_order.action routing:
                ├── 'delivery' → init_delivery_summary()
                │   └── init_delivery RPC → delivery_summary created
                │       └── [DB triggers → delivery flow continues]
                └── 'takeaway' → init_takeaway_summary()
                    └── init_takeaway RPC → takeaway_summary created
                        └── [DB triggers → takeaway flow continues]

2b. Pay-at-Restaurant Path (takeaway only)
    └── POST /pay-at-restaurant/{rest_ref}
        ├── payment_status → 'pay_at_rest'
        ├── handle_payment_complete() → restaurant notified
        └── init_takeaway_summary()
            └── init_takeaway RPC → takeaway_summary created
                └── [DB triggers → takeaway flow continues]
```

---

## Webhook Endpoints

### Order Hooks (`/order-hooks/`)

| Endpoint | Method | Purpose | Source |
|----------|--------|---------|--------|
| `/order-hooks/get-min-order-value` | GET | Minimum order value by coordinates | `order_hooks.py:52` |
| `/order-hooks/get-min-order-value-by-postcode` | GET | Minimum order value by postcode | `order_hooks.py:127` |
| `/order-hooks/create-order/{rest_ref}` | POST | Create order and return payment URL | `order_hooks.py:212` |
| `/order-hooks/postcode-validator/{postcode}` | GET | Validate UK postcode | `order_hooks.py:304` |
| `/order-hooks/capture-address` | POST | Capture customer address and notify restaurant | `order_hooks.py:338` |
| `/order-hooks/get-active-thread/{rest_ref}/{recipient}` | GET | Proxy active thread lookup to restaurant | `order_hooks.py:413` |
| `/order-hooks/terminate-stale-active-threads` | POST | Trigger stale thread cleanup on restaurant | `order_hooks.py:385` |

### Payment Hooks (`/payment-hooks/`)

| Endpoint | Method | Trigger Source | Purpose | Source |
|----------|--------|----------------|---------|--------|
| `/payment-hooks/payment-complete` | POST | Stripe webhook | Process payment, route to delivery/takeaway init | `payment_hooks.py:96` |
| `/payment-hooks/payment-complete-test/{order_number}` | POST | Manual/test | Test init without Stripe | `payment_hooks.py:141` |
| `/payment-hooks/pay-at-restaurant/{rest_ref}` | POST | Restaurant frontend | Pay-at-restaurant takeaway orders | `payment_hooks.py:171` |

### External Webhooks Called

| Webhook Path | Called By | Purpose |
|--------------|----------|---------|
| `order-payment-complete/{recipient}/{thread_id}` | `handle_payment_complete()` | Notify restaurant of payment |
| `order-address-update/{recipient}` | `capture_address()` | Notify restaurant of customer address |
| `get-active-thread/{rest_ref}/{recipient}` | `get_active_thread()` | Proxy thread lookup |
| `terminate-stale-active-threads` | `terminate_stale_active_threads()` | Trigger stale thread cleanup |

---

*End of Payment and Order Flow Documentation*
