# Takeaway Restaurant Confirmation Flow — Implementation Plan

## Context

Takeaway orders (`food_order.action = "takeaway"`) already exist in the system but currently have no restaurant confirmation or pickup time flow. Delivery orders use `delivery_summary` + DB triggers + webhook handlers for this. We need the same restaurant confirmation flow for takeaway, diverging only after pickup time is confirmed: **notify the customer with pickup time** (instead of dispatching a rider).

**Approach**: Create a `takeaway_summary` table with its own triggers and webhook handlers, while reusing existing WhatsApp sender functions and callback handlers. The `order_type` field is threaded through callback button payloads so shared handlers (`/PickupTime`, `/RestaurantOrder`) can route to the correct table without extra DB lookups.

**Pay-at-restaurant**: Takeaway orders may have `food_order.payment_status = "pay_at_rest"`, meaning no Stripe payment occurs. These orders need a direct entry point (no payment webhook to trigger them) and the decline flow must skip payment cancellation.

---

## Step 1: Create `takeaway_summary` Table + Triggers

**New file**: `ordelo_datamodels/takeaway_summary.sql`

Table schema (lean — no customer location, no rider fields, but keeps `rest_address` for customer pickup notification):

```sql
CREATE TABLE takeaway_summary (
    order_number          VARCHAR(100) PRIMARY KEY,
    rest_id               VARCHAR(12) NOT NULL,
    rest_name             TEXT NOT NULL,
    rest_address          TEXT NOT NULL,
    town                  VARCHAR(255) NOT NULL,
    customer_id           VARCHAR(50) NOT NULL,
    customer_name         TEXT NOT NULL,
    restaurant_confirmation_status VARCHAR(50) NOT NULL DEFAULT 'restaurant_unconfirmed'
        CHECK (restaurant_confirmation_status IN (
            'restaurant_unconfirmed','restaurant_accept','restaurant_decline',
            'restaurant_timedout','auto_accept','auto_decline')),
    restaurant_update_dtts TIMESTAMP WITH TIME ZONE,
    restaurant_admin       VARCHAR(12),
    status                 VARCHAR(50) NOT NULL
        CHECK (status IN ('restaurant_unconfirmed','pickup_confirmed','declined','completed')),
    rest_confirmation_code INTEGER NOT NULL,
    rest_prep_time_minutes INTEGER,
    rest_confirmation_method VARCHAR(20),
    restaurant_msg_id      VARCHAR(255),
    customer_msg_id        VARCHAR(255),
    pickup_time            TIMESTAMP WITH TIME ZONE,
    pickup_date            DATE NOT NULL DEFAULT CURRENT_DATE,
    rest_ref               VARCHAR(20) GENERATED ALWAYS AS (SPLIT_PART(order_number, '-', 1)) STORED,
    dt                     DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts                   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

**Fields added vs original Plan A** (carried from Plan C):
- `rest_address`, `town` — needed for customer pickup notification ("Pick up at [address]")
- `rest_prep_time_minutes` — tracks restaurant's stated prep time
- `declined` added to `status` CHECK — for restaurant decline flow

**Fields omitted vs `delivery_summary`**:
- `customer_lon`, `customer_lat`, `customer_address` — customer picks up, no routing needed
- `rider_msg_id` — no rider
- `cust_confirmation_code` — no rider handoff verification

**Trigger**: `trigger_takeaway_restaurant_updates` — mirrors `trigger_restaurant_updates` on `delivery_summary`.

**Trigger function**: `takeaway_restaurant_updates_whook()` — mirrors `restaurant_updates_whook()` (`ordelo_datamodels/summary.sql:89`) but:
- Reads from `takeaway_summary` (no customer location fields in JSON)
- POSTs to `/takeaway-hooks/restaurant-confirmation-request`
- Same debug_log pattern for traceability

---

## Step 2: Create `init_takeaway()` SQL Function

**New file**: `ordelo_datamodels/jobs_n_functions/init_takeaway.sql`

Mirrors `init_delivery()` (`ordelo_datamodels/jobs_n_functions/init_delivery.sql`) but:
- Inserts into `takeaway_summary` (not `delivery_summary`)
- Includes `rest_address` and `town` from `restaurant_master`
- No customer location fields (customer_lon, customer_lat, customer_address)
- No `cust_confirmation_code`
- Status starts as `'restaurant_unconfirmed'`
- Still fetches restaurant details from `restaurant_master` and customer name from `customer_master`
- Still generates `rest_confirmation_code`

---

## Step 3: Update `process_restaurant_confirmation.sql`

**File**: `ordelo_datamodels/jobs_n_functions/process_restaurant_confirmation.sql`

Add a second CTE that scans `takeaway_summary` for timed-out records using the same logic:
- `restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept')`
- `pickup_time IS NULL`
- Time since `dtts` exceeds configured timeout
- Uses same config key pattern: `{rest_ref}_RESTAURANT_CONFIRMATION_TIMEOUT_TIME` → `RESTAURANT_CONFIRMATION_TIMEOUT_TIME` → fallback `5` minutes

Union results from both CTEs so the same pg_cron job (every 5s) handles timeouts for both tables.

---

## Step 4: Create `takeaway_hooks.py` Router

**New file**: `watomation/routers/takeaway_hooks.py`

Structure mirrors `delivery_hooks.py` (`watomation/routers/delivery_hooks.py`) with these handlers:

| Handler | Behavior |
|---|---|
| `_handle_restaurant_unconfirmed` | Sends order confirmation to admins via `send_restaurant_order_confirmation()` with `order_type="takeaway"`. Same as delivery. |
| `_handle_restaurant_accept` | Sends pickup time options to admins via `send_restaurant_pickup_time()` with `order_type="takeaway"`. Same as delivery. |
| `_handle_restaurant_decline` | Updates `takeaway_summary.status` to `'declined'`. **Notifies customer** that the restaurant declined their order. **Cancels payment** via `cancel_payment()` (reuse from `delivery_hooks.py:196`) **only if `payment_status != "pay_at_rest"`** — check `food_order.payment_status` from the webhook payload. |
| `_handle_restaurant_timedout` | Auto-sets `pickup_time` (+30 mins from `dtts`), sets `restaurant_confirmation_status='auto_accept'`, `status='pickup_confirmed'`. **Notifies customer with pickup time via WhatsApp**. Notifies admin of auto-accept. |

**Customer WhatsApp notification content** (for pickup_confirmed and auto_accept):
```
Your order {order_number} is confirmed!

Pickup time: {pickup_time formatted}
Restaurant: {rest_name}
Address: {rest_address}
```

**Customer WhatsApp notification content** (for decline — card payment):
```
Sorry, your order {order_number} could not be accepted by {rest_name}.
Your payment has been cancelled.
```

**Customer WhatsApp notification content** (for decline — pay at restaurant):
```
Sorry, your order {order_number} could not be accepted by {rest_name}.
```

**Pydantic models**: `TakeawaySummaryData` (lean version of `DeliverySummaryData` — no customer location, no rider fields, includes `rest_address` and `town`), reuses `RestaurantMasterData`, `FoodOrder`, `OrderItem` from existing imports.

**Endpoints**:

1. `POST /takeaway-hooks/restaurant-confirmation-request` — triggered by DB trigger on `takeaway_summary`, routes by `trigger_reason`, same pattern as delivery.

2. `POST /takeaway-hooks/init-takeaway-order` — **new, for pay-at-restaurant orders**. Called directly from `order_hooks.py` when `action="takeaway"` and `payment_status="pay_at_rest"` (no Stripe webhook will fire for these). Calls `init_takeaway` RPC to create the `takeaway_summary` record, which then fires the trigger chain as normal.

```python
@router.post("/init-takeaway-order")
async def init_takeaway_order(
    background_tasks: BackgroundTasks,
    payload: dict = Depends(get_payload),
):
    order_number = payload["order_number"]
    customer_id = payload["customer_id"]
    background_tasks.add_task(init_takeaway_summary, order_number, customer_id)
    return {"status": "accepted", "order_number": order_number}
```

The `init_takeaway_summary()` function (calling `init_takeaway` RPC) lives in this file and is also reused by `payment_hooks.py` for card-payment takeaway orders.

---

## Step 5: Add `order_type` to Callback Button Payloads

**File**: `utils_common/waba_utils/wa_senders.py`

Since `CallbackButtonData` uses `extra="allow"` (line 81), no model changes needed. Update the sender functions:

### `send_restaurant_order_confirmation()` (line 545)
- Already receives `order_type` param
- Add `order_type=order_type` to both `accept_button` and `decline_button` `CallbackButtonData` constructors
- Existing delivery callers already pass `order_type="delivery"`, so backward compatible

### `send_restaurant_pickup_time()` (line 89)
- Add `order_type: str = "delivery"` parameter (default preserves backward compat)
- Add `order_type=order_type` to the `CallbackButtonData` constructor inside the button loop

---

## Step 6: Update Shared Callback Handlers

**File**: `watomation/on_callback_wa_handler.py`

### `_update_restaurant_order_status()` (line 213)
- Add `order_type` parameter (default `"delivery"`)
- If `order_type == "takeaway"`: update `takeaway_summary` instead of `delivery_summary`
- Gate condition stays the same: `.eq("restaurant_confirmation_status", "restaurant_unconfirmed")`

### `restaurant_order_accept_decline_handler()` (line 248)
- Extract `order_type` from `callback_data` (default to `"delivery"` for backward compat with existing in-flight buttons)
- Pass `order_type` to `_update_restaurant_order_status()`

### `handle_pickup_time_selection()` (line 275)
- Extract `order_type` from `callback_data` (default to `"delivery"`)
- If `order_type == "delivery"`: existing logic — update `delivery_summary`, set `status='unassigned'`
- If `order_type == "takeaway"`: update `takeaway_summary` with `pickup_time` + `status='pickup_confirmed'`, then **send customer WhatsApp notification** with order_number, pickup time, restaurant name + address (fetched from the takeaway_summary row or from the callback context)

**Backward compatibility**: Callbacks already in the wild (sent before this deploy) won't have `order_type` in their payload. Using `getattr(callback_data, 'order_type', 'delivery')` ensures they route to `delivery_summary` as before.

---

## Step 7: Branch Entry Points by Order Type + Payment Status

There are now **two entry paths** into the takeaway flow depending on how the customer pays:

### Path A: Card payment (Stripe) — `payment_hooks.py`

**File**: `watomation/routers/payment_hooks.py`

`payment_complete_path()` (line 88) — after fetching `food_order`, branch:

```python
if food_order.action == "delivery":
    background_tasks.add_task(init_delivery_summary, food_order.order_number, food_order.recipient)
elif food_order.action == "takeaway":
    background_tasks.add_task(init_takeaway_summary, food_order.order_number, food_order.recipient)
```

Import `init_takeaway_summary` from `takeaway_hooks.py` (where the function is defined alongside the router).

### Path B: Pay at restaurant — `order_hooks.py`

**File**: `watomation/routers/order_hooks.py`

In `create_order()` (line 232), after the existing payment URL branching (lines 283-286), add a third branch for pay-at-restaurant:

```python
if food_order.action == "delivery":
    payment_intent_url = await generate_payment_intent_url(food_order)
elif food_order.action == "takeaway" and food_order.payment_status == "pay_at_rest":
    # No payment URL needed — init takeaway immediately
    payment_intent_url = None
    background_tasks.add_task(init_takeaway_summary, food_order.order_number, food_order.recipient)
else:
    # takeaway with card payment — Stripe auto-capture, init happens in payment_hooks
    payment_intent_url = await generate_automatic_payment_url(food_order)
```

Alternatively, `create_order()` can POST to `/takeaway-hooks/init-takeaway-order` instead of calling `init_takeaway_summary` directly — either works; direct call is simpler.

### `init_takeaway_summary()` function

Defined in `takeaway_hooks.py`, mirrors `init_delivery_summary()` (`payment_hooks.py:72`) but calls `init_takeaway` RPC. Imported by `payment_hooks.py` and `order_hooks.py` as needed.

---

## Step 8: Register Router

**File**: `watomation/fapp_ordelo_agent.py`

- Import `takeaway_hooks` module
- Register: `app.include_router(takeaway_hooks.router, prefix="/takeaway-hooks")` (after line 117, alongside other routers)

---

## File Change Summary

| File | Action |
|---|---|
| `ordelo_datamodels/takeaway_summary.sql` | **NEW** — table + trigger + trigger function |
| `ordelo_datamodels/jobs_n_functions/init_takeaway.sql` | **NEW** — `init_takeaway()` SQL function |
| `ordelo_datamodels/jobs_n_functions/process_restaurant_confirmation.sql` | **EDIT** — add takeaway_summary timeout CTE |
| `watomation/routers/takeaway_hooks.py` | **NEW** — takeaway webhook handlers + TakeawaySummaryData model |
| `utils_common/waba_utils/wa_senders.py` | **EDIT** — thread `order_type` into callback payloads (2 functions) |
| `watomation/on_callback_wa_handler.py` | **EDIT** — route callbacks to correct table by `order_type` (3 functions) |
| `watomation/routers/payment_hooks.py` | **EDIT** — branch init by `food_order.action`, import `init_takeaway_summary` |
| `watomation/routers/order_hooks.py` | **EDIT** — add pay-at-restaurant branch for takeaway (skip payment URL, init takeaway directly) |
| `watomation/fapp_ordelo_agent.py` | **EDIT** — register takeaway_hooks router |

---

## Test Cases

### Delivery Regression
1. Existing delivery confirmation flow works unchanged end-to-end.
2. Existing `/PickupTime` and `/RestaurantOrder` callbacks without `order_type` field default to `delivery_summary`.

### Takeaway Happy Path
3. Payment complete → `init_takeaway` inserts row → `restaurant_unconfirmed` webhook fires → admin gets WhatsApp with takeaway emoji → accept → `/PickupTime` → `takeaway_summary` updated → **customer receives pickup time WA message**.

### Takeaway Decline (card payment)
4a. Admin declines → `takeaway_summary.status` set to `'declined'` → customer notified of decline + payment cancellation → `cancel_payment()` called.

### Takeaway Decline (pay at restaurant)
4b. Admin declines → `takeaway_summary.status` set to `'declined'` → customer notified of decline (no payment mention) → `cancel_payment()` NOT called.

### Takeaway Timeout
5. No response within configured timeout → `process_restaurant_confirmation()` sets `restaurant_timedout` → webhook fires → auto-accept sets `pickup_time` (+30 mins) → **customer notified** → admin notified of auto-accept.

### Callback Idempotency
6. Repeated `/PickupTime` tap does not double-update — gated by `.eq("restaurant_confirmation_status", "restaurant_accept")`.

### Wrong-Mode Safety
7. Delivery callback cannot update `takeaway_summary` and vice versa — `order_type` in payload determines target table.

### Payment Hook Branch
8. `food_order.action="delivery"` triggers only `init_delivery`.
9. `food_order.action="takeaway"` with card payment triggers `init_takeaway` via `payment_hooks.py`.

### Pay-at-Restaurant Path
10. `food_order.action="takeaway"` with `payment_status="pay_at_rest"` triggers `init_takeaway` directly from `order_hooks.py` (no Stripe webhook involved).
11. Decline for pay-at-rest order does NOT call `cancel_payment()`.

---

## Acceptance Criteria

1. Takeaway orders do not depend on or write to `delivery_summary`.
2. Delivery behavior remains completely unchanged.
3. Restaurant confirmation flow is functionally identical for both modes from the admin's perspective (same WhatsApp messages, same buttons).
4. Customer receives pickup-time WhatsApp message immediately after admin selects pickup time for a takeaway order.
5. Customer receives decline notification if restaurant declines. Payment cancellation only occurs when `payment_status != "pay_at_rest"`.
6. Timeout auto-accept works for takeaway using the same config keys and fallback logic.

---

## Assumptions

1. Canonical order types are exactly `"delivery"` and `"takeaway"` (via `food_order.action`).
2. Takeaway payment modes: card (Stripe auto-capture) or `"pay_at_rest"` (no Stripe involvement).
3. Takeaway decline policy: notify customer always; cancel payment only if card payment (not `pay_at_rest`).
4. Customer notification channel: WhatsApp message sent from the callback handler / takeaway_hooks handler (no separate trigger needed).
5. Timeout config keys reuse existing pattern: `{rest_ref}_RESTAURANT_CONFIRMATION_TIMEOUT_TIME` → `RESTAURANT_CONFIRMATION_TIMEOUT_TIME` → default `5` minutes.
6. No changes to rider dispatch, inflight, or location code in this rollout.
7. `cancel_payment()` from `delivery_hooks.py` is reusable for takeaway (it operates on `food_order` by `order_number`, table-agnostic).
