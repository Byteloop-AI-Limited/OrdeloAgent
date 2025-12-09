# Restaurant Confirmation Flow (WhatsApp)

Guide to the restaurant prep-time confirmation flow that runs before rider dispatch.

## Components
- `watomation/routers/delivery_hooks.py`: Webhook that sends the WhatsApp requests and reacts to status changes.
- `utils_common/waba_utils/wa_templates/restaurant_confirmation_template.py`: Builds the Accept/Decline template and callback payload.
- `utils_common/waba_utils/wa_senders.py`: Sends the pickup-time buttons (5/15/25 min) via `send_restaurant_pickup_time()`.
- `watomation/on_callback_wa_handler.py`: Handles WhatsApp button callbacks (`/RestaurantOrder-*`, `/PickupTime`, `/restaurantConfirmation`).
- `ordelo_datamodels/jobs_n_functions/handle_restaurant_confirmation.sql`: Supabase RPC that finalises the confirmation and kicks off dispatch; timeout handled in `job_restaurant_confirmation_timeout.sql`.

## Flow
1) **Order inserted → DB trigger**  
   `delivery_summary.status` starts as `restaurant_unconfirmed` (via `init_delivery`). The trigger `restaurant_confirmation_whook()` posts to `/delivery-hooks/restaurant-confirmation-request` with `trigger_reason=restaurant_unconfirmed`.

2) **Send Accept/Decline to restaurant** (`_handle_restaurant_unconfirmed` in `delivery_hooks.py`)  
   - Builds order summary and calls `send_restaurant_order_confirmation()` (template).  
   - Buttons carry `action="/RestaurantOrder-Accept"` or `"/RestaurantOrder-Decline"` plus `order_number`/`order_time`.

3) **Accept/Decline callback** (`restaurant_order_accept_decline_handler` in `on_callback_wa_handler.py`)  
   - Accept → async update of `delivery_summary.status` to `restaurant_accept`.  
   - Decline → status `restaurant_decline`.  
   These status updates retrigger the webhook in step 1 with new `trigger_reason`.

4) **After Accept: ask for prep time** (`_handle_restaurant_accept` in `delivery_hooks.py`)  
   - For each admin phone, calls `send_restaurant_pickup_time()` (`wa_senders.py` lines ~67-69) to send three time options (default 5/15/25 mins from order time).  
   - Buttons use `action="/PickupTime"` and include `order_number` + chosen `pickup_time` ISO string.

5) **Pickup time callback** (`handle_pickup_time_selection` in `on_callback_wa_handler.py`)  
   - Reads `/PickupTime` payload, sets `delivery_summary.pickup_time` and moves status from `restaurant_accept` to `unassigned`.  
   - Once status is `unassigned`, the normal dispatch creation runs.

6) **Alternative single-step confirmation** (`handle_restaurant_confirmation` in `on_callback_wa_handler.py`)  
   - Used for buttons that send `/restaurantConfirmation` with `prep_time_minutes`.  
   - Replies with a confirmation message, then calls Supabase RPC `handle_restaurant_confirmation(order_number, prep_time_minutes)` in the background.  
   - The SQL function sets `rest_confirmed_at`, `rest_prep_time_minutes`, `rest_confirmation_method='manual'`, recomputes `pickup_time`, flips status to `unassigned`, and calls `process_delivery()`.

7) **Decline path** (`_handle_restaurant_decline` in `delivery_hooks.py`)  
   - Updates status to `unassigned` to prevent the job from staying blocked in `restaurant_decline`.

8) **Timeout safety net**  
   - `job_restaurant_confirmation_timeout.sql` runs via pg_cron; any order still in `restaurant_unconfirmed` after the configured window is auto-confirmed with a default prep time (25 minutes) and moved to `unassigned`.

## Status Transitions (happy path)
`restaurant_unconfirmed` → (Accept) → `restaurant_accept` → (pickup time selected) → `unassigned` → dispatch to riders.

## Tweaks / Hotspots
- Prep-time options: adjust `intervals_mins` in `send_restaurant_pickup_time()` (`utils_common/waba_utils/wa_senders.py`).
- Template text or payload: edit `send_restaurant_order_confirmation()` in `utils_common/waba_utils/wa_templates/restaurant_confirmation_template.py`.
- Callback filters are registered in `watomation/fapp_ordelo_agent.py` (`IS_RESTAURANT_ORDER_ACCEPT_DECLINE`, `IS_PICKUP_TIME`, `IS_RESTAURANT_CONFIRMATION`).
