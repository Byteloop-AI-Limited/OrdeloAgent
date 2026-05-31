# Callback Button Handlers

**Version:** 1.0
**Last Updated:** 2026-02-14

WhatsApp callback button handlers registered in `watomation/fapp_ordelo_agent.py`. Each handler responds to a specific button tap from a rider, restaurant admin, or system admin.

For the delivery dispatch callback flow in detail, see `docs/dispatch_flow.md` (Step 4).
For pickup time callback flow in detail, see `docs/pickup_time_logic.md`.

---

## Handler Registry

All handlers are defined in `watomation/on_callback_wa_handler.py` and registered via `wa.add_handlers()` in `watomation/fapp_ordelo_agent.py`.

| Filter | Handler Function | Button Source | Actor |
|---|---|---|---|
| `/dispatchResponse` | `dispatch_response()` | `wa_send_delivery_dispatch_request_to_rider()` in `delivery_hooks.py` | Rider |
| `/riderLocationRequest` | `rider_request_location()` | `_send_delivery_instructions()` in `agent_app_handlers.py` | Rider |
| `/shiftAvailability` | `handle_shift_availability()` | `enquire_shift_availability()` / `enquire_shift_availability_non_template()` in `wa_senders.py` | Rider |
| `/adminAvailability` | `handle_admin_availability()` | `enquire_admin_availability()` in `wa_senders.py` | Restaurant Admin |
| `/RestaurantOrder` | `restaurant_order_accept_decline_handler()` | `send_restaurant_order_confirmation()` in `wa_senders.py` | Restaurant Admin |
| `/PickupTime` | `handle_pickup_time_selection()` | `send_restaurant_pickup_time()` in `wa_senders.py` | Restaurant Admin |
| `/AdminCollectionReady` | `admin_collection_ready()` | `admin_order_reciept()` in `wa_senders.py` | Restaurant Admin |
| `/AdminAdjustPickupTime` | `admin_adjust_pickup_time()` | `admin_order_reciept()` in `wa_senders.py` (adjust buttons) | Restaurant Admin |
| `/AdminTakeawayReady` | `admin_takeaway_ready()` | Takeaway order receipt message | Restaurant Admin |

---

## Handler Details

### `dispatch_response` -- Rider Accept/Decline Dispatch

- **Filter:** `IS_DISPATCH_RESPONSE` -- `filters.contains("/dispatchResponse")`
- **Callback data fields:** `command`, `dispatch_id`, `order_number`, `status` (`"accepted"` or `"declined"`), plus `rider_id` set from `msg.sender`
- **Source:** Buttons sent by `wa_send_delivery_dispatch_request_to_rider()` in `watomation/routers/delivery_hooks.py`

Behavior:

1. Parses callback JSON, removes `command`, sets `rider_id` to sender.
2. Validates the order exists in `delivery_summary`.
   - Missing order -> rider told "This job is no longer available".
3. Checks `delivery_inflight` for the same `order_number`:
   - **Same rider, not declining their own dispatch** -> rider told "You are already on a job".
   - **Same rider, declining their own inflight dispatch** -> falls through to cancel logic via `initial_handle_of_rider_response()`. This allows an assigned rider to decline pre-pickup, triggering the cancel flow.
   - **Different rider already inflight** -> rider told "this job was picked up by another rider".
4. Delegates to `initial_handle_of_rider_response()` in `ordelo/agent_app_handlers.py` to record accept/decline on `delivery_dispatch`.

### `rider_request_location` -- Rider Location Request

- **Filter:** `IS_LOCATION_REQUEST` -- `filters.contains("/riderLocationRequest")`
- **Callback data fields:** `action`, `recipient`, `human_msg` (e.g., "Send me the pickup location" or "Send me the dropoff location")
- **Source:** Buttons sent by `_send_delivery_instructions()` in `ordelo/agent_app_handlers.py`

Behavior:

1. Parses callback JSON.
2. Invokes `run_rider_agent_w_custom_msg()` with the `recipient` and `human_msg` from callback data.
3. The rider agent graph processes the location request and responds via WhatsApp.

### `handle_shift_availability` -- Rider Shift Start/End

- **Filter:** `IS_SHIFT_AVAILABILITY` -- `filters.contains("/shiftAvailability")`
- **Callback data fields:** `action`, `recipient`, `human_msg` (`"Yes"` or `"No"`)
- **Source:** `enquire_shift_availability()` (template version) or `enquire_shift_availability_non_template()` in `utils_common/waba_utils/wa_senders.py`

Behavior:

1. Parses callback JSON to get `recipient` and `human_msg`.
2. **"Yes" (start shift):**
   - Updates `rider_master.is_in_shift = True` and `shift_response_dtts = now()`.
   - Rider told "You will receive notifications for new jobs."
3. **"No" (end shift):**
   - **Inflight guard:** Checks `delivery_inflight` for active jobs by this rider.
     - If rider is currently on a job -> rider told "Please complete the job first" and shift remains active.
   - If not inflight -> updates `rider_master.is_in_shift = False`.
   - Rider told "You will not receive job notifications for the next 24 hrs."

### `handle_admin_availability` -- Admin Order Notification Opt-In

- **Filter:** `IS_ADMIN_AVAILABILITY` -- `filters.contains("/adminAvailability")`
- **Callback data fields:** `action`, `recipient`
- **Source:** `enquire_admin_availability()` in `utils_common/waba_utils/wa_senders.py` (template `alert_order_notification_resolve`)

Behavior:

1. Parses callback JSON to get `recipient`.
2. Replies "You will receive notification for new orders for the next 24 hrs!"
3. Logs confirmation.

### `restaurant_order_accept_decline_handler` -- Restaurant Accept/Decline Order

- **Filter:** `IS_RESTAURANT_ORDER_ACCEPT_DECLINE` -- `filters.contains("/RestaurantOrder")`
- **Callback data fields:** `action` (`"/RestaurantOrder-Accept"` or `"/RestaurantOrder-Decline"`), `order_number`, `order_time`, `order_type` (`"delivery"` or `"takeaway"`)
- **Source:** `send_restaurant_order_confirmation()` in `utils_common/waba_utils/wa_senders.py`
- **Shared handler:** Used for both delivery and takeaway orders. Called from `delivery_hooks.py` and `takeaway_hooks.py`.

Behavior:

1. Parses callback data into `CallbackButtonData`.
2. **Accept** -> fires `_update_restaurant_order_status()` as `asyncio.create_task` with status `"restaurant_accept"`.
3. **Decline** -> fires `_update_restaurant_order_status()` as `asyncio.create_task` with status `"restaurant_decline"`.

`_update_restaurant_order_status()`:
- Updates the target table (`delivery_summary` or `takeaway_summary` based on `order_type`).
- Sets `restaurant_confirmation_status` and `restaurant_admin`.
- Gated by `restaurant_confirmation_status = 'restaurant_unconfirmed'` to prevent duplicate updates.
- If no rows matched (already confirmed) -> replies "Order Already Accepted".

### `handle_pickup_time_selection` -- Admin Pickup Time Selection

- **Filter:** `IS_PICKUP_TIME` -- `filters.contains("/PickupTime")`
- **Callback data fields:** `action`, `order_number`, `pickup_time`, `order_type` (`"delivery"` or `"takeaway"`)
- **Source:** `send_restaurant_pickup_time()` in `utils_common/waba_utils/wa_senders.py`
- **Shared handler:** Used for both delivery and takeaway orders.

Behavior:

1. Parses callback data into `CallbackButtonData`.
2. Determines target table and status:
   - Delivery: `delivery_summary`, status -> `"unassigned"`
   - Takeaway: `takeaway_summary`, status -> `"pickup_confirmed"`
3. Updates the target table with `pickup_time`, `status`, `restaurant_admin`, `restaurant_update_dtts`.
4. Update is gated by `restaurant_confirmation_status = 'restaurant_accept'`.
5. **Takeaway-specific:** Also sends the customer a WhatsApp confirmation with pickup time, restaurant name, and address.
6. If no rows matched (already updated) -> replies "Pickup time already updated".

See `docs/pickup_time_logic.md` for the full pickup time flow including timeout and auto-accept paths.

### `admin_collection_ready` -- Admin Notifies Food Ready for Pickup

- **Filter:** `filters.contains("/AdminCollectionReady")` (inline in `fapp_ordelo_agent.py`, not a module-level constant)
- **Callback data fields:** `action`, `rider_id`, `restaurant_name`, `order_id`
- **Source:** `admin_order_reciept()` in `utils_common/waba_utils/wa_senders.py`. The "Ready - Notify Rider" button is sent to restaurant admins as part of the inflight order receipt.

Behavior:

1. Parses callback data into `CallbackButtonData`.
2. Invokes `run_rider_agent_w_custom_msg()` with the `rider_id` from callback data and a message instructing the agent to call `notify_food_ready_for_pickup`.
3. The rider agent notifies the rider to hurry to the restaurant for pickup.

### `admin_adjust_pickup_time` -- Admin Adjusts Pickup Time (Inflight Delivery)

- **Filter:** `IS_ADMIN_ADJUST_PICKUP_TIME` -- `filters.contains("/AdminAdjustPickupTime")`
- **Callback data fields:** `action`, `order_number`, `pickup_time` (precomputed ISO timestamp for +10 or +20 min)
- **Source:** Buttons sent by `admin_order_reciept()` in `utils_common/waba_utils/wa_senders.py`, included in the inflight order receipt sent to restaurant admins

Behavior:

1. Parses callback JSON to get `order_number` and `pickup_time`.
2. Updates `delivery_summary`:
   - `pickup_time` = new value from callback
   - `restaurant_confirmation_status` = `'restaurant_pickuptime_adjusted'`
   - `restaurant_admin` = callback sender
   - `restaurant_update_dtts` = now (UTC)
3. Replies to admin with the formatted UK local time.
4. The DB update fires `trigger_restaurant_updates` → `_handle_restaurant_pickuptime_adjusted()` → rider agent `notify_pickup_time_adjusted` tool. See `docs/pickup_time_logic.md` section C for the full chain.

Only updates pickup time; does **not** change `delivery_summary.status` (the delivery remains inflight).

### `admin_takeaway_ready` -- Admin Marks Takeaway Order as Ready

- **Filter:** `IS_ADMIN_TAKEAWAY_READY` -- `filters.contains("/AdminTakeawayReady")`
- **Callback data fields:** `action`, `order_number`, `recipient` (customer phone), `rest_ref`
- **Source:** Takeaway order receipt message sent to restaurant admins

Behavior:

1. Parses callback JSON to extract `order_number`, `recipient`, and `rest_ref` (falling back to the prefix of `order_number` if `rest_ref` is absent).
2. Derives `order_id` by stripping the restaurant prefix from `order_number` (e.g., `ELAS-KDDV-21` → `KDDV-21`).
3. Builds a payload: `{ order_id, order_number, recipient, admin_id, event: "admin_takeaway_ready", event_dtts }`.
4. Fetches the restaurant webhook URL via `get_restaurant_webhook_url_async(rest_ref, "order-takeaway-ready")`.
5. POSTs the payload to `{webhook_url}/{order_id}` via `httpx`.
6. Replies to admin with a confirmation or an error message if the webhook call fails.

This is a pass-through to the restaurant's own service — no `takeaway_summary` status change happens in OrdeloAgent itself.

---

## Handler Signature Differences

Most handlers follow the signature `(wa: WhatsApp, msg: Message)`. The exception is:

- `admin_collection_ready(msg: WhatsApp, callback: CallbackButton[CallbackButtonData])` -- uses the `CallbackButton` type directly, with parameter names `msg` (WhatsApp client) and `callback` (the button event).

---

## Registration Order

Handlers are registered in `wa.add_handlers()` in the following order. PyWA evaluates handlers in registration order and stops at the first match:

1. `admin_collection_ready` -- `/AdminCollectionReady`
2. `dispatch_response` -- `/dispatchResponse`
3. `rider_request_location` -- `/riderLocationRequest`
4. `handle_shift_availability` -- `/shiftAvailability`
5. `handle_admin_availability` -- `/adminAvailability`
6. `restaurant_order_accept_decline_handler` -- `/RestaurantOrder`
7. `handle_pickup_time_selection` -- `/PickupTime`
8. `admin_adjust_pickup_time` -- `/AdminAdjustPickupTime`
9. `admin_takeaway_ready` -- `/AdminTakeawayReady`

All filters use `filters.contains()` with `ignore_case=False` (except `admin_collection_ready` which uses the default). Since each callback action string is unique, registration order does not affect routing.
