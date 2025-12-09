# Restaurant Confirmation Flow (WhatsApp)

Guide to the restaurant prep-time confirmation flow that runs before rider dispatch.

## Schema Changes (v2)

The `delivery_summary` table now has two separate status columns:
- **`restaurant_confirmation_status`**: Tracks restaurant's response (`restaurant_unconfirmed`, `restaurant_accept`, `restaurant_decline`, `restaurant_timedout`)
- **`status`**: Tracks delivery lifecycle (`restaurant_unconfirmed`, `unassigned`, `timedout`, `assigned`, `completed`)

New columns added:
- `restaurant_update_dtts`: Timestamp when restaurant confirmation status was last updated (replaces `rest_confirmed_at`)
- `restaurant_admin`: Phone number of the admin who confirmed the order
- `restaurant_msg_id`, `rider_msg_id`, `customer_msg_id`: WhatsApp message IDs for tracking communications

## Components
- `watomation/routers/delivery_hooks.py`: Webhook that sends the WhatsApp requests and reacts to `restaurant_confirmation_status` changes.
- `utils_common/waba_utils/wa_templates/restaurant_confirmation_template.py`: Builds the Accept/Decline template and callback payload.
- `utils_common/waba_utils/wa_senders.py`: Sends the pickup-time buttons (5/15/25 min) via `send_restaurant_pickup_time()`.
- `watomation/on_callback_wa_handler.py`: Handles WhatsApp button callbacks (`/RestaurantOrder-*`, `/PickupTime`, `/restaurantConfirmation`).
- `ordelo_datamodels/jobs_n_functions/handle_restaurant_confirmation.sql`: Supabase RPC that finalises the confirmation and kicks off dispatch; timeout handled in `job_restaurant_confirmation_timeout.sql`.

## Flow
1) **Order inserted → DB trigger**  
   `delivery_summary.restaurant_confirmation_status` starts as `restaurant_unconfirmed` (via `init_delivery`). The trigger `restaurant_confirmation_whook()` fires on `restaurant_confirmation_status` changes and posts to `/delivery-hooks/restaurant-confirmation-request` with `trigger_reason=restaurant_unconfirmed`.

2) **Send Accept/Decline to restaurant** (`_handle_restaurant_unconfirmed` in `delivery_hooks.py`)  
   - Builds order summary and calls `send_restaurant_order_confirmation()` (template).  
   - Buttons carry `action="/RestaurantOrder-Accept"` or `"/RestaurantOrder-Decline"` plus `order_number`/`order_time`.

3) **Accept/Decline callback** (`restaurant_order_accept_decline_handler` in `on_callback_wa_handler.py`)  
   - Accept → async update of `delivery_summary.restaurant_confirmation_status` to `restaurant_accept`.  
   - Decline → `restaurant_confirmation_status` to `restaurant_decline`.  
   These status updates retrigger the webhook in step 1 with new `trigger_reason`.

4) **After Accept: ask for prep time** (`_handle_restaurant_accept` in `delivery_hooks.py`)  
   - For each admin phone, calls `send_restaurant_pickup_time()` (`wa_senders.py` lines ~67-69) to send three time options (default 5/15/25 mins from order time).  
   - Buttons use `action="/PickupTime"` and include `order_number` + chosen `pickup_time` ISO string.

5) **Pickup time callback** (`handle_pickup_time_selection` in `on_callback_wa_handler.py`)  
   - Reads `/PickupTime` payload, sets `delivery_summary.pickup_time` and moves `status` to `unassigned`.  
   - Once `status` is `unassigned`, the normal dispatch creation runs via `process_delivery()`.

6) **Alternative single-step confirmation** (`handle_restaurant_confirmation` in `on_callback_wa_handler.py`)  
   - Used for buttons that send `/restaurantConfirmation` with `prep_time_minutes`.  
   - Replies with a confirmation message, then calls Supabase RPC `handle_restaurant_confirmation(order_number, prep_time_minutes)` in the background.  
   - The SQL function sets `rest_confirmed_at`, `rest_prep_time_minutes`, `rest_confirmation_method='manual'`, recomputes `pickup_time`, flips `status` to `unassigned`, and calls `process_delivery()`.

7) **Decline path** (`_handle_restaurant_decline` in `delivery_hooks.py`)  
   - Updates `status` to `unassigned` to prevent the job from staying blocked.

8) **Timeout path** (`_handle_restaurant_timedout` in `delivery_hooks.py`)  
   - Triggered when `restaurant_confirmation_status` is updated to `restaurant_timedout` by the timeout job.
   - Logs the timeout event for monitoring.
   - Future: Can auto-confirm with default prep time and notify restaurant admins.

9) **Timeout safety net**  
   - `job_restaurant_confirmation_timeout.sql` runs via pg_cron; any order still in `restaurant_confirmation_status='restaurant_unconfirmed'` after the configured window updates `restaurant_confirmation_status` to `restaurant_timedout`.

## Status Transitions

### restaurant_confirmation_status (restaurant response tracking)
`restaurant_unconfirmed` → (Accept) → `restaurant_accept`
`restaurant_unconfirmed` → (Decline) → `restaurant_decline`
`restaurant_unconfirmed` → (Timeout) → `restaurant_timedout`

### status (delivery lifecycle)
`restaurant_unconfirmed` → (pickup time selected) → `unassigned` → dispatch to riders → `assigned` → `completed`
`restaurant_unconfirmed` → (decline) → `unassigned`
`unassigned` → (all vehicles timed out) → `timedout`

## Tweaks / Hotspots
- Prep-time options: adjust `intervals_mins` in `send_restaurant_pickup_time()` (`utils_common/waba_utils/wa_senders.py`).
- Template text or payload: edit `send_restaurant_order_confirmation()` in `utils_common/waba_utils/wa_templates/restaurant_confirmation_template.py`.
- Callback filters are registered in `watomation/fapp_ordelo_agent.py` (`IS_RESTAURANT_ORDER_ACCEPT_DECLINE`, `IS_PICKUP_TIME`, `IS_RESTAURANT_CONFIRMATION`).
- Trigger condition: `trigger_restaurant_updates` fires on `restaurant_confirmation_status` column changes in `ordelo_datamodels/summary.sql`.
