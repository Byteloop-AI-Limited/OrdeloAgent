# Ordelo Dispatch Flow

**Version:** 1.2
**Last Updated:** 2026-09-03

This document focuses on the **dispatch portion** of the Ordelo delivery workflow: from dispatch creation, through rider accept/decline, to inflight initialization and missed‑dispatch notifications.

For the full end‑to‑end delivery journey, see `docs/delivery_process.md` (Phases 3–5).

---

## Components Involved

- **PostgreSQL jobs/functions**
  - Dispatch creation and assignment jobs create and finalize dispatches.
  - Separate scheduled “availability enquiry” jobs also exist (rider shift + restaurant admin enquiries); see `docs/delivery_process.md` for details.
- **PostgreSQL triggers**
  - Fire webhooks when `delivery_dispatch` and `delivery_inflight` change.
- **FastAPI delivery hooks**
  - Receive webhook payloads and fan out WhatsApp/graph actions.
- **WhatsApp callbacks**
  - Riders respond to dispatch offers via interactive buttons.

Key source files:

- `ordelo_datamodels/dispatch.sql`
- `watomation/routers/delivery_hooks.py`
- `watomation/on_callback_wa_handler.py`
- `ordelo_datamodels/inflight.sql`

---

## High‑Level Flow

1. **Dispatch rows are created** in `delivery_dispatch` (typically by scheduled SQL job).
2. **DB trigger batches those inserts** and POSTs them to `/delivery-hooks/delivery-dispatch`.
3. **API sends WhatsApp offers** to riders with Accept/Decline buttons.
4. **Riders tap a button** → WhatsApp callback `/dispatchResponse`.
5. **Callback handler records accept/decline** on `delivery_dispatch`.
6. **Assignment job picks first accepted dispatch**, marks it assigned, and inserts `delivery_inflight`.
7. **Inflight trigger initializes tracking/agent graph** and notifies “missed” riders.

---

## Step‑By‑Step Detail

### 1. Dispatch Creation (DB)

Dispatch offers are inserted into `delivery_dispatch`. Each row represents one rider being offered the job.

Table definition and status enum live in `ordelo_datamodels/dispatch.sql`:

- Key fields: `dispatch_id`, `order_number`, `rider_id`, `rider_payout`, `vehicle_type`, `distance`, `status`.
- Initial status for new rows is typically `unassigned`.

### 2. Dispatch Webhook Trigger (DB → API)

`ordelo_datamodels/dispatch.sql` defines a **statement‑level AFTER INSERT trigger**:

- Trigger: `trigger_delivery_dispatch_whook`
- Function: `delivery_dispatch_whook_statement()`
- Fires once per INSERT statement and uses `REFERENCING NEW TABLE AS new_rows`.

What it does:

1. Joins newly inserted dispatch rows (`new_rows`) to `delivery_detail` and `delivery_summary`.
2. Builds a bulk payload:

   ```json
   { "bulk_dispatch": [ { "dispatch_id": ..., "order_number": ..., "rider_id": ..., "pickup_time": ..., "rest_*": ..., "customer_*": ... } ] }
   ```

3. POSTs once to:

   - `/delivery-hooks/delivery-dispatch`
   - Base URL from `ordelo_config.ORDELO_APP_URL` (fallback to `https://rider-agent.ordelo.app`).

This batching avoids one webhook per rider in large fan‑outs.

### 3. Dispatch Hook Handler (API → WhatsApp)

`watomation/routers/delivery_hooks.py` exposes:

- Endpoint: `POST /delivery-hooks/delivery-dispatch`
- Handler: `delivery_dispatch_hook()`

Behavior:

1. Reads `bulk_dispatch` list from the payload.
2. For each dispatch, schedules a background task:
   - `wa_send_delivery_dispatch_request_to_rider(recipient=rider_id, delivery_summary=d, dispatch_id=dispatch_id)`
3. Returns immediately with `{ "status": "success" }` (empty payloads short‑circuit to success).

`wa_send_delivery_dispatch_request_to_rider()` sends a WhatsApp message including:

- Order, pickup/dropoff, payout, distance, vehicle type, pickup time.
- Two buttons:
  - **Accept** → callback data `{ "command": "/dispatchResponse", "dispatch_id": ..., "order_number": ..., "status": "accepted" }`
  - **Decline** → same but `status: "declined"`.

**Overwatch customer filtering:** Before dispatching, the handler checks if the customer is in the `overwatch_list` (from `ordelo_config`). If so, dispatch messages are sent **only** to the rider whose `rider_id` matches the `customer_id` (i.e., overwatch/test customers can only be served by themselves). All other riders are silently skipped for that order.

### 4. Rider Response Callback (WhatsApp → API)

`watomation/on_callback_wa_handler.py` defines:

- Filter: `IS_DISPATCH_RESPONSE`
- Handler: `dispatch_response()`

On button tap:

1. Parses callback JSON (`msg.data`), removes `"command"`, and sets `"rider_id"` to the sender.
2. Validates the order still exists in `delivery_summary`.
   - If missing → rider is told the job is no longer available.
3. Checks `delivery_inflight` for the same `order_number` to prevent double‑assignment.
   - If already inflight with same rider → rider is told they’re already on the job.
   - If inflight with another rider → rider is told job was taken.
4. Delegates to `initial_handle_of_rider_response()` to record accept/decline.

### 5. Recording Accept/Decline (API → DB)

`initial_handle_of_rider_response()` (in `ordelo/agent_app_handlers.py`, called by `dispatch_response()`) updates `delivery_dispatch`:

- If rider **declines** → `delivery_dispatch.status = 'declined'`.
- If rider **accepts**:
  - Only when `delivery_summary.status == 'unassigned'`
  - Updates `delivery_dispatch.status = 'accepted'`.
  - If the order is already `completed` or `timedout`, the rider is told it’s unavailable and no accept is recorded.

This keeps acceptance lightweight and lets assignment happen in DB jobs.

### 6. Assignment + Inflight Insert (DB)

A scheduled assignment job (see `docs/delivery_process.md` Phase 4 for full SQL) selects the **first accepted dispatch**:

1. Finds earliest `delivery_dispatch` with `status = 'accepted'`.
2. Updates:
   - `delivery_dispatch.status = 'assigned'`
   - `delivery_detail.status = 'assigned'` with chosen `dispatch_id`/`rider_id`
   - `delivery_summary.status = 'assigned'`
3. Inserts one row into `delivery_inflight`.

### 7. Inflight Trigger + Graph Init (DB → API)

`ordelo_datamodels/inflight.sql` defines a **row‑level AFTER INSERT trigger**:

- Trigger: `trigger_delivery_inflight_whook`
- Function: `delivery_inflight_whook()`
- Webhook: `POST /delivery-hooks/delivery-inflight-graph-init`

Payload includes:

```json
{
  "delivery_inflight": [ { "dispatch_id": ..., "order_number": ..., "rider_id": ..., "customer_id": ... } ],
  "delivery_summary": { ... },
  "rider_master": { "rider_id": ..., "rider_name": ... }
}
```

The receiving handler is `delivery_inflight_graph_init_hook()` in `watomation/routers/delivery_hooks.py`:

- Background tasks, in scheduling order:
  - `capture_delivery_payment()` → Stripe capture (also issues the receipt print job).
  - `post_rider_event_inflight()` → restaurant webhook “rider‑inflight”.
  - `admin_order_reciept()` → admin notification.
  - `init_ordelo_graph()` → LangGraph rider agent/tracking initialization.
  - `notify_overwatch()` → logs the inflight event to the overwatch channel.

### 8. Missed Dispatch Notifications (DB → API → WhatsApp)

Still inside `delivery_inflight_whook()` (`ordelo_datamodels/inflight.sql`):

1. Calls `notify_missed_dispatches()`, which finds **other accepted dispatches** for the now‑assigned order.
2. POSTs:
   - `/delivery-hooks/notify-missed-dispatches`

`notify_missed_dispatches_hook()` in `watomation/routers/delivery_hooks.py`:

- Sends a WhatsApp apology to each missed rider.
- Marks their `delivery_dispatch.status = 'missed'` so they are not re‑notified.

---

## Status Transitions Summary

`delivery_dispatch.status` follows:

`unassigned` → (`accepted` | `declined` | `timedout`) → `assigned` → `pickedup` → `completed`

Additional side‑paths:

- `accepted` (non‑selected rider) → `missed`
- `assigned` → `declined` (pre‑pickup cancellation via `dispatch_cancel_before_pickup`)

`delivery_summary.status` relevant to dispatch:

`unassigned` → `assigned` → (`completed` | `timedout`)

Pre‑pickup cancellation path: `assigned` → `unassigned` (order re‑enters dispatch cycle)

---

## Pre‑Pickup Cancellation Flow

When a rider cannot complete pickup **before** restaurant code verification, the system supports cancellation that reopens the order for re‑dispatch.

### Trigger

The rider tells the agent they cannot pick up. The agent calls the `cancel_delivery_before_pickup` tool (in `ordelo/agents/rider_agent.py`).

### Step‑by‑Step

1. **Rider tool invocation** — `cancel_delivery_before_pickup` reads `dispatch_id` from agent state and calls Supabase RPC `dispatch_cancel_before_pickup(p_dispatch_id)`.

2. **RPC execution** (`ordelo_datamodels/jobs_n_functions/dispatch_cancel_before_pickup.sql`):
   - Guards: dispatch must exist and `delivery_dispatch.status` must be `'assigned'` (if already `'pickedup'`, cancellation is rejected).
   - Sets the cancelling rider's `delivery_dispatch.status = 'declined'` and `status_update_dtts = CURRENT_TIMESTAMP`. **This row is deliberately kept** — it is what excludes that rider from the next round.
   - Deletes the `delivery_inflight` row for this dispatch (frees the rider).
   - **Deletes all other `delivery_dispatch` rows for the order.** Without this, `get_available_riders()` would keep excluding every previously-notified rider and the re-dispatch would find nobody.
   - **Deletes all `delivery_detail` rows for the order** — not just the cancelled one — so `process_delivery()` rebuilds the vehicle-type cascade from rank 1 instead of resuming mid-cascade.
   - Sets `delivery_summary.status = 'unassigned'` and `redispatch_dtts = NOW()`.

3. **Reason capture** — The tool sets `awaiting_cancel_reason = True` in agent state and asks the rider for a reason. When the rider replies:
   - `agent_node` detects `awaiting_cancel_reason` and synthesizes a `terminate_delivery_job` tool call with `reason_for_decline` set to the rider's message.
   - `terminate_delivery_job` persists the reason on `delivery_dispatch.reason_for_decline`.

4. **Thread closure** — `terminate_delivery_job` makes the thread inactive via `ThreadHandler.make_threads_inactive()` and sends the rider a plain “Delivery job completed ✅, thank you.” text. No tracking link or button is sent.

### Effect on Re‑Dispatch

Once `delivery_summary.status` is back to `unassigned`:

- `process_delivery()` (pg_cron, every 5s) picks up the order. Because the RPC deleted every `delivery_detail` row, the vehicle-type cascade is rebuilt from rank 1 — a vehicle type that had already timed out gets another chance.
- The delivery timeout is measured from `COALESCE(delivery_summary.redispatch_dtts, delivery_summary.dtts)`, and the RPC stamped `redispatch_dtts = NOW()`, so the re-dispatch gets a full timeout window rather than inheriting the original order's elapsed clock.
- `job_create_dispatch()` (pg_cron, every 5s) creates new dispatch offers for available riders.
- The cancelled rider is **excluded** from future dispatch batches for this order: their `delivery_dispatch` row survives with `status = 'declined'`, and `get_available_riders()` excludes any rider with an existing dispatch row for the same order.
- Every **other** rider becomes eligible again, because the RPC deleted their dispatch rows. This is what makes the re-offer round actually reach riders who were previously notified.

### Status Transitions

```
delivery_dispatch:   assigned → declined   (cancelling rider's row, KEPT)
delivery_dispatch:   all other rows for the order → deleted
delivery_detail:     all rows for the order → deleted (cascade rebuilt from rank 1)
delivery_summary:    assigned → unassigned, redispatch_dtts = NOW()
delivery_inflight:   row deleted
```

---

## Notes / Race Conditions

- Multiple riders can accept; **only the first accepted dispatch is assigned**. Others are transitioned to `missed` after inflight insert.
- If the assigned rider cancels before pickup, the system reverts to `unassigned` and re‑dispatches.
- **No repeat offers within a round:** `get_available_riders()` excludes any rider who already has a `delivery_dispatch` row for the order, regardless of status. This prevents repeated offers on every cron tick while a `delivery_detail` remains `unassigned`. A *new* round is opened only by an explicit event that clears those rows — today, `dispatch_cancel_before_pickup`.
- Acceptance is ignored if the order has already moved to `completed`/`timedout` (rider gets a “no longer available” message).
- The dispatch webhook is **statement‑level**, so a batch insert results in a single API call.

---

## Re‑Offer Approach

Re‑offering the same order to riders is useful after pre‑pickup cancellation or long timeouts, but **must be explicit** to avoid infinite re‑dispatching.

The naive change (exclude only `status='declined'` riders) makes *all* previous offers eligible again. Since `job_create_dispatch()` runs every ~5s and `delivery_detail.status` stays `unassigned` until assignment, that would recreate dispatch rows and send WhatsApp offers on every tick.

### Implemented: explicit redispatch window (pre‑pickup cancellation only)

`dispatch_cancel_before_pickup` is the one resume event wired up today. It follows the explicit‑window pattern:

- The default exclusion is kept — `get_available_riders()` still excludes every rider with a dispatch row for the order.
- The RPC **deletes** the order's dispatch rows (keeping only the cancelling rider's `declined` row) and all its `delivery_detail` rows, then sets `delivery_summary.status='unassigned'` and `redispatch_dtts=NOW()`.
- The next cron tick therefore creates *one* fresh batch, not a new batch every tick.

Note the difference from the original sketch: the implementation keeps only the **declining** rider's row rather than all `declined` rows, so a rider who declined an earlier round can be offered the job again.

### Not implemented: dispatch attempt state (for timeout‑driven re‑offers)

There is still no re‑offer path for orders that simply time out without a cancellation. That would need:

- A `delivery_detail.status='dispatched'` (or a `last_dispatch_dtts` + attempt counter).
- `job_create_dispatch()` moving details from `unassigned` → `dispatched` after inserting a batch.
- A separate timeout/resume job moving `dispatched` → `unassigned` when it's time to re‑offer.
- `get_available_riders()` excluding only `declined` riders *within that attempt*.

This keeps re‑offers bounded and predictable without relying on a delete‑and‑rebuild.
