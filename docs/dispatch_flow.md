# Ordelo Dispatch Flow

**Version:** 1.0  
**Last Updated:** 2025-12-12

This document focuses on the **dispatch portion** of the Ordelo delivery workflow: from dispatch creation, through rider accept/decline, to inflight initialization and missed‑dispatch notifications.

For the full end‑to‑end delivery journey, see `docs/delivery_process.md` (Phases 3–5).

---

## Components Involved

- **PostgreSQL jobs/functions**
  - Dispatch creation and assignment jobs create and finalize dispatches.
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

- Background tasks:
  - `post_rider_event_inflight()` → restaurant webhook “rider‑inflight”.
  - `admin_order_reciept()` → admin notification.
  - `capture_payment()` → Stripe capture.
  - `init_ordelo_graph()` → LangGraph rider agent/tracking initialization.

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

`unassigned` → (`accepted` | `declined` | `timedout`) → `assigned` → `completed`

Additional terminal side‑path:

`accepted` (non‑selected rider) → `missed`

`delivery_summary.status` relevant to dispatch:

`unassigned` → `assigned` → (`completed` | `timedout`)

---

## Notes / Race Conditions

- Multiple riders can accept; **only the first accepted dispatch is assigned**. Others are transitioned to `missed` after inflight insert.
- Acceptance is ignored if the order has already moved to `completed`/`timedout` (rider gets a “no longer available” message).
- The dispatch webhook is **statement‑level**, so a batch insert results in a single API call.

