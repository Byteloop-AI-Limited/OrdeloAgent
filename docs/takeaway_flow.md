# Ordelo Takeaway Flow

**Version:** 1.1
**Last Updated:** 2026-08-18

This document covers the takeaway order lifecycle within OrdeloAgent, from initialization through restaurant confirmation to pickup time confirmation. For delivery-specific flows, see `docs/delivery_process.md`.

---

## Table of Contents

1. [Overview](#overview)
2. [Key Differences from Delivery](#key-differences-from-delivery)
3. [Database Tables](#database-tables)
4. [Initialization Paths](#initialization-paths)
   - [Stripe Payment Path](#stripe-payment-path)
   - [Pay-at-Restaurant Path](#pay-at-restaurant-path)
5. [Restaurant Confirmation Flow](#restaurant-confirmation-flow)
6. [Pickup Time Selection](#pickup-time-selection)
7. [Restaurant Decline Path](#restaurant-decline-path)
8. [Restaurant Timeout Path](#restaurant-timeout-path)
9. [Status Transitions](#status-transitions)
10. [Triggers and Webhooks](#triggers-and-webhooks)
11. [Webhook Endpoints](#webhook-endpoints)

---

## Overview

Takeaway orders allow customers to place an order and collect it from the restaurant themselves. There is no rider dispatch, no live tracking, and no delivery inflight phase. The flow focuses on restaurant confirmation, pickup time selection, and customer notification.

### High-Level Flow

```
Order Created → Payment (Stripe or pay-at-restaurant) → init_takeaway() RPC
  → takeaway_summary INSERT → DB trigger → Restaurant Confirmation Request
  → Restaurant Accept → Pickup Time Selection → pickup_confirmed
  → DB trigger → External Restaurant Notification
```

For `restaurant_master.auto_accept=true`, initialization resolves a configured
pickup time and inserts the order as `auto_accept` / `pickup_confirmed`. The
insert-time pickup trigger retains payment/print, restaurant webhook, and
overwatch work, and sends the restaurant-admin takeaway receipt.

---

## Key Differences from Delivery

| Aspect | Delivery | Takeaway |
|--------|----------|----------|
| Summary table | `delivery_summary` | `takeaway_summary` |
| Init RPC | `init_delivery()` | `init_takeaway()` |
| Rider dispatch | Yes (Phases 3-5) | No |
| Live tracking | Yes (OwnTracks) | No |
| Terminal success status | `completed` | `pickup_confirmed` |
| Payment capture | Manual capture at inflight (rider assigned) | Automatic capture at payment (no manual mode) |
| Pay-at-restaurant option | Not supported | Supported (`payment_status = 'pay_at_rest'`) |
| Confirmation code verification | Restaurant + customer codes via rider agent | Not applicable |

---

## Database Tables

### takeaway_summary

The `takeaway_summary` table is the master record for each takeaway order. It is created by the `init_takeaway()` RPC function.

Key fields (from `TakeawaySummaryData` in `watomation/routers/takeaway_hooks.py`):

| Field | Type | Description |
|-------|------|-------------|
| `order_number` | `str` | Unique order identifier (e.g., `ELAS-KDDV-21`) |
| `rest_id` | `str` | Restaurant identifier |
| `rest_name` | `str` | Restaurant display name |
| `rest_address` | `str` | Restaurant address |
| `town` | `str` | Restaurant town |
| `customer_id` | `str` | Customer phone number |
| `customer_name` | `str` | Customer display name |
| `restaurant_confirmation_status` | `str` | Confirmation workflow state |
| `status` | `str` | Overall takeaway status |
| `rest_confirmation_code` | `int` | Confirmation code for restaurant |
| `rest_prep_time_minutes` | `int?` | Estimated preparation time |
| `pickup_time` | `str?` | ISO timestamp of pickup time (NULL until set) |
| `pickup_date` | `str` | Date of pickup |
| `rest_ref` | `str?` | Restaurant reference code |
| `dt` | `str` | Order date |
| `dtts` | `str` | Order timestamp |

### Status Values

#### takeaway_summary.status

| Status | Description |
|--------|-------------|
| `restaurant_unconfirmed` | Initial state, waiting for restaurant response |
| `pickup_confirmed` | Restaurant accepted and pickup time is set |
| `declined` | Restaurant declined the order |

#### takeaway_summary.restaurant_confirmation_status

| Status | Description |
|--------|-------------|
| `restaurant_unconfirmed` | Initial state, awaiting restaurant response |
| `restaurant_accept` | Restaurant accepted, awaiting pickup time selection |
| `restaurant_decline` | Restaurant declined the order |
| `restaurant_timedout` | No response within timeout period |
| `auto_accept` | System auto-accepted after timeout |

---

## Initialization Paths

Both paths converge on the same RPC call: `init_takeaway(p_cust_id, p_order_number)`, which creates the `takeaway_summary` record. The difference is how payment is handled before initialization.

### Stripe Payment Path

For customers paying online via Stripe.

**Flow:**

1. Order is created via `POST /order-hooks/create-order/{rest_ref}` with `order_type = "takeaway"`
2. Payment URL is generated using `generate_takeaway_manual_payment_url()` with `action="collection"` and manual capture
3. Customer authorizes payment on Stripe checkout; the payment service stores the PaymentIntent and does not print
4. Stripe calls `POST /payment-hooks/payment-complete`
5. Handler updates `food_order.payment_status` to `requires_capture`
6. Since `food_order.action == "takeaway"`, the handler calls `init_takeaway_summary()` as a background task
7. `init_takeaway_summary()` invokes the `init_takeaway` RPC
8. The first finalized `pickup_time` triggers capture, payout, and one collection receipt

**Source:** `watomation/routers/payment_hooks.py:96-135` (`payment_complete_path`)

### Pay-at-Restaurant Path

For customers who will pay at the restaurant counter.

**Flow:**

1. Restaurant frontend calls `POST /payment-hooks/pay-at-restaurant/{rest_ref}`
2. Handler validates `order_type == "takeaway"` (pay-at-restaurant is takeaway-only)
3. `food_order.payment_status` is updated to `pay_at_rest`
4. `handle_payment_complete()` notifies the restaurant service
5. `init_takeaway_summary()` is called as a background task
6. `init_takeaway_summary()` invokes the `init_takeaway` RPC

**Source:** `watomation/routers/payment_hooks.py:171-215` (`pay_at_restaurant`)

There is also a direct entrypoint at `POST /takeaway-hooks/init-takeaway-order` that accepts `order_number` and `customer_id` and calls `init_takeaway_summary()` directly.

**Source:** `watomation/routers/takeaway_hooks.py:477-489` (`init_takeaway_order`)

---

## Restaurant Confirmation Flow

After `init_takeaway()` creates the `takeaway_summary` record with `restaurant_confirmation_status = 'restaurant_unconfirmed'`, a DB trigger fires a webhook to the agent.

### Confirmation Request Trigger

**Trigger:** Fires on INSERT or UPDATE of `restaurant_confirmation_status` on `takeaway_summary`

**Webhook:** `POST /takeaway-hooks/restaurant-confirmation-request`

**Payload model:** `TakeawayConfirmationPayload`

```json
{
  "trigger_reason": "restaurant_unconfirmed|restaurant_accept|restaurant_decline|restaurant_timedout",
  "takeaway_summary": { ... },
  "restaurant_master": { ... },
  "food_order": { ... },
  "order_items": [ ... ]
}
```

### Webhook Handler

**File:** `watomation/routers/takeaway_hooks.py`

**Endpoint:** `POST /takeaway-hooks/restaurant-confirmation-request`

**Handler:** `restaurant_confirmation_flow()`

All handlers run as background tasks to avoid DB trigger HTTP timeouts.

| trigger_reason | Handler | Action |
|----------------|---------|--------|
| `restaurant_unconfirmed` | `_handle_restaurant_unconfirmed()` | Sends Accept/Decline order confirmation to all restaurant admins via WhatsApp |
| `restaurant_accept` | `_handle_restaurant_accept()` | Sends pickup time selection (5/15/25 min intervals) to all restaurant admins |
| `restaurant_decline` | `_handle_restaurant_decline()` | Updates status to `declined`, cancels payment if applicable, notifies customer |
| `restaurant_timedout` | `_handle_restaurant_timedout()` | Auto-accepts with pickup time set from `PICKUP_DEFAULT_TIME` config (default 30 mins from order time), notifies admins and customer |

### WhatsApp Callback Handlers

Restaurant admins respond to the confirmation request via WhatsApp interactive buttons. The callback handlers in `watomation/on_callback_wa_handler.py` handle both delivery and takeaway orders by checking `order_type`:

| Callback | Handler | Takeaway Behavior |
|----------|---------|-------------------|
| `/RestaurantOrder-Accept` | `restaurant_order_accept_decline_handler()` | Updates `takeaway_summary.restaurant_confirmation_status` to `restaurant_accept` |
| `/RestaurantOrder-Decline` | `restaurant_order_accept_decline_handler()` | Updates `takeaway_summary.restaurant_confirmation_status` to `restaurant_decline` |
| `/PickupTime` | `handle_pickup_time_selection()` | Updates `takeaway_summary.pickup_time` and sets `status` to `pickup_confirmed` |

**Source:** `watomation/on_callback_wa_handler.py:226`, `watomation/on_callback_wa_handler.py:294`

---

## Pickup Time Selection

When the restaurant accepts the order, admins receive a WhatsApp message with pickup time options at 5, 15, and 25 minute intervals from the order time.

**Source:** `watomation/routers/takeaway_hooks.py:176-206` (`_handle_restaurant_accept`)

When an admin selects a pickup time:

1. `handle_pickup_time_selection()` in `on_callback_wa_handler.py` updates `takeaway_summary`:
   - Sets `pickup_time` to the selected ISO timestamp
   - Sets `status` to `pickup_confirmed`
   - Sets `restaurant_confirmation_status` to `restaurant_accept`
2. Customer receives a pickup confirmation message via `_send_customer_pickup_confirmation()` with the pickup time, restaurant name, and address
3. A DB trigger (`trigger_takeaway_pickup_time_set`) fires when `pickup_time` changes from NULL to a value. Configured auto-accept uses the companion INSERT trigger when summary creation already has a pickup time.

### Pickup Time Webhook (External Restaurant Notification)

**Triggers:** `trigger_takeaway_pickup_time_set` on NULL-to-non-NULL UPDATE and `trigger_takeaway_pickup_time_insert` on configured-auto non-null INSERT.

**Source Function:** `takeaway_pickup_time_whook()` in `ordelo_datamodels/takeaway_summary.sql`

**Webhook:** `POST /takeaway-hooks/pickup-time-updated`

**Handler:** `pickup_time_updated_hook()` schedules manual capture, the external pickup-time webhook, the operational admin receipt, and Overwatch notification as background tasks.

**Actions:** the first task captures an online payment with `payment_mode=capture` and `action=collection`; it retries only an explicit missing-PaymentIntent lookup after 2 and 5 seconds. The pickup-time event is then posted to the external restaurant service:

```
POST {restaurant_webhook_url}/order-pickup-time-updated
{
  "takeaway_summary": { ... },
  "restaurant_master": { ... }
}
```

**Source:** `watomation/routers/takeaway_hooks.py` (`pickup_time_updated_hook`, `capture_takeaway_payment`, and `_post_pickup_time_event`)

---

## Restaurant Decline Path

When a restaurant declines a takeaway order:

1. `_handle_restaurant_decline()` updates `takeaway_summary.status` to `declined`
2. If `food_order.payment_status != "pay_at_rest"` (i.e., customer paid via Stripe):
   - Calls `cancel_payment()` (imported from `watomation/routers/delivery_hooks.py`) to cancel the Stripe payment
   - Sends customer message: "Sorry, your order {order_number} could not be accepted by {rest_name}. Your payment has been cancelled."
3. If `payment_status == "pay_at_rest"`:
   - Sends customer message without payment cancellation notice

**Source:** `watomation/routers/takeaway_hooks.py:209-250` (`_handle_restaurant_decline`)

---

## Restaurant Timeout Path

When a restaurant does not respond within the configured timeout period:

1. A `pg_cron` job (similar to delivery's `process_restaurant_confirmation`) updates `restaurant_confirmation_status` to `restaurant_timedout`
2. The DB trigger fires the webhook with `trigger_reason = "restaurant_timedout"`
3. `_handle_restaurant_timedout()` auto-accepts the order:
   - Sets pickup time to **`PICKUP_DEFAULT_TIME` minutes after order time** (restaurant-specific `{rest_ref}_PICKUP_DEFAULT_TIME` checked first, then global `PICKUP_DEFAULT_TIME`, then hardcoded fallback of 30 minutes)
   - Updates `takeaway_summary.status` to `pickup_confirmed`
   - Updates `restaurant_confirmation_status` to `auto_accept`
   - Notifies all restaurant admins that the order was auto-accepted
   - Sends customer a pickup confirmation with the auto-set pickup time

**Source:** `watomation/routers/takeaway_hooks.py:253-300` (`_handle_restaurant_timedout`)

---

## Status Transitions

### Complete Takeaway Order Journey

```
1. init_takeaway() RPC
   └── takeaway_summary.status = 'restaurant_unconfirmed'
       takeaway_summary.restaurant_confirmation_status = 'restaurant_unconfirmed'
       └── [Trigger → WhatsApp Accept/Decline to restaurant admins]

2. Restaurant Response
   ├── Accept → restaurant_confirmation_status = 'restaurant_accept'
   │   └── [WhatsApp pickup time selection: 5/15/25 min]
   │       └── Pickup time selected
   │           ├── status = 'pickup_confirmed'
   │           ├── [Customer pickup confirmation message]
   │           └── [Trigger: pickup_time_updated → external restaurant notification]
   ├── Decline → restaurant_confirmation_status = 'restaurant_decline'
   │   └── status = 'declined'
   │       ├── [Cancel Stripe payment if not pay-at-restaurant]
   │       └── [Customer decline notification]
   └── Timeout → restaurant_confirmation_status = 'restaurant_timedout'
       └── restaurant_confirmation_status = 'auto_accept'
           └── status = 'pickup_confirmed'
               ├── pickup_time = order_time + PICKUP_DEFAULT_TIME min
               ├── [Admin auto-accept notification]
               ├── [Customer pickup confirmation message]
               └── [Trigger: pickup_time_updated → external restaurant notification]
```

---

## Triggers and Webhooks

| Trigger | Table | Condition | Function | Webhook |
|---------|-------|-----------|----------|---------|
| (restaurant confirmation trigger) | `takeaway_summary` | INSERT or UPDATE of `restaurant_confirmation_status` | (takeaway equivalent of `restaurant_updates_whook()`) | `/takeaway-hooks/restaurant-confirmation-request` |
| `trigger_takeaway_pickup_time_set` | `takeaway_summary` | UPDATE `pickup_time` from NULL to non-NULL | `takeaway_pickup_time_whook()` | `/takeaway-hooks/pickup-time-updated` |

---

## Webhook Endpoints

| Endpoint | Method | Trigger Source | Handler | Source File |
|----------|--------|----------------|---------|-------------|
| `/takeaway-hooks/restaurant-confirmation-request` | POST | DB trigger on `takeaway_summary` | `restaurant_confirmation_flow()` | `watomation/routers/takeaway_hooks.py:303` |
| `/takeaway-hooks/pickup-time-updated` | POST | `trigger_takeaway_pickup_time_set` | `pickup_time_updated_hook()` | `watomation/routers/takeaway_hooks.py:431` |
| `/takeaway-hooks/init-takeaway-order` | POST | Direct call (pay-at-restaurant) | `init_takeaway_order()` | `watomation/routers/takeaway_hooks.py:477` |
| `/payment-hooks/payment-complete` | POST | Stripe webhook | `payment_complete_path()` | `watomation/routers/payment_hooks.py:96` |
| `/payment-hooks/pay-at-restaurant/{rest_ref}` | POST | Restaurant frontend | `pay_at_restaurant()` | `watomation/routers/payment_hooks.py:171` |

---

*End of Takeaway Flow Documentation*
