# Ordelo Delivery Process

**Version:** 3.1
**Last Updated:** 2026-02-14

This document provides a comprehensive reference for the Ordelo delivery workflow, covering the complete journey from order creation through delivery completion, including all database triggers, scheduled jobs, and webhook integrations.

---

## Table of Contents

1. [High-Level Overview](#high-level-overview)
2. [Database Tables](#database-tables)
3. [Workflow Phases](#workflow-phases)
   - [Phase 1: Order Creation](#phase-1-order-creation-init_delivery)
   - [Phase 2: Restaurant Confirmation](#phase-2-restaurant-confirmation)
   - [Phase 3: Dispatch Creation](#phase-3-dispatch-creation-process_delivery--job_create_dispatch)
   - [Phase 4: Rider Assignment](#phase-4-rider-assignment-job_assign_dispatch)
   - [Phase 5: Delivery Execution](#phase-5-delivery-execution-inflight)
   - [Phase 6: Completion](#phase-6-completion-dispatch_complete_func)
4. [Triggers and Webhooks](#triggers-and-webhooks)
5. [Scheduled Jobs (pg_cron)](#scheduled-jobs-pg_cron)
6. [Status Transitions](#status-transitions)
7. [Configuration Keys](#configuration-keys)
8. [Workflow Diagram](#workflow-diagram)
9. [SQL Files Reference](#sql-files-reference)

---

## High-Level Overview

The Ordelo delivery workflow orchestrates food delivery from order placement to completion using:

- **PostgreSQL Functions & Triggers**: Core business logic executed at the database level
- **pg_cron Scheduled Jobs**: Periodic tasks for dispatch creation, assignment, and timeout handling
- **FastAPI Webhooks**: HTTP endpoints called by database triggers for complex operations
- **WhatsApp Integration**: Rider and restaurant notifications via WhatsApp Business API (see [Embedded Signup Guide](../utils_common/waba_es/embedded_signup_guide.md) for WABA onboarding)
- **LangGraph Agent**: AI-powered rider assistance during delivery execution

### Key Phases

```
Order Created → Restaurant Confirms → Dispatch to Riders → Rider Accepts → 
Rider Assigned → Delivery Inflight → Delivery Completed
```

---

## Database Tables

| Table | Purpose |
|-------|---------|
| `delivery_summary` | Master record for each order with restaurant/customer details, status, and confirmation codes |
| `delivery_detail` | Per-vehicle-type delivery attempt records |
| `delivery_dispatch` | Individual dispatch offers sent to riders |
| `delivery_inflight` | Active deliveries currently being executed |
| `rider_location` | Live GPS tracking data from riders |
| `rider_location_event` | Zone transition events (approaching restaurant/customer) |

### delivery_summary Status Values

| Status | Description |
|--------|-------------|
| `restaurant_unconfirmed` | Waiting for restaurant to confirm order |
| `unassigned` | Ready for rider dispatch |
| `assigned` | Rider has been assigned |
| `timedout` | All dispatch attempts failed |
| `completed` | Delivery successfully completed |

### restaurant_confirmation_status Values

| Status | Description |
|--------|-------------|
| `restaurant_unconfirmed` | Initial state, awaiting restaurant response |
| `restaurant_accept` | Restaurant accepted, awaiting pickup time selection |
| `restaurant_decline` | Restaurant declined the order |
| `restaurant_timedout` | No response within timeout period |
| `auto_accept` | System auto-accepted after timeout |

### delivery_detail Status Values

| Status | Description |
|--------|-------------|
| `unassigned` | Awaiting rider dispatch |
| `vehicle_type_timedout` | Current vehicle type exhausted, trying next |
| `assigned` | Rider assigned to this delivery |
| `completed` | Delivery completed |

### delivery_dispatch Status Values

| Status | Description |
|--------|-------------|
| `unassigned` | Dispatch sent, awaiting rider response |
| `accepted` | Rider accepted the job |
| `declined` | Rider declined the job |
| `timedout` | No response within 30 seconds |
| `missed` | Job was taken by another rider |
| `assigned` | Rider is assigned and active |
| `pickedup` | Food pickup confirmed (restaurant code verified) |
| `completed` | Delivery completed |

---

## Workflow Phases

### Phase 1: Order Creation (`init_delivery`)

**File:** `ordelo_datamodels/jobs_n_functions/init_delivery.sql`

**Invocation:** Called by external payment service after successful payment

**Function:** `init_delivery(p_cust_id VARCHAR, p_order_number VARCHAR)`

**Purpose:**
- Creates `delivery_summary` record with restaurant and customer details
- Generates confirmation codes for restaurant and customer verification
- Sets initial status to `restaurant_unconfirmed`

**Dependencies:**
- Reads: `customer_master`, `restaurant_master`, `ordelo_config`
- Writes: `delivery_summary`

**Side Effects:**
- Triggers `trigger_restaurant_updates` → `restaurant_updates_whook()` → POST `/delivery-hooks/restaurant-confirmation-request`

---

### Phase 2: Restaurant Confirmation

This phase ensures restaurants confirm orders and provide estimated prep time before riders are dispatched.

#### 2a. Confirmation Request Trigger

**File:** `ordelo_datamodels/summary.sql`

**Trigger:** `trigger_restaurant_updates`
```sql
AFTER INSERT OR UPDATE OF restaurant_confirmation_status ON delivery_summary
WHEN (NEW.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline', 'restaurant_timedout'))
```

**Function:** `restaurant_updates_whook()`

**Webhook:** POST `/delivery-hooks/restaurant-confirmation-request`

**Payload:**
```json
{
  "trigger_reason": "restaurant_unconfirmed|restaurant_accept|restaurant_decline|restaurant_timedout",
  "delivery_summary": { ... },
  "restaurant_master": { ... },
  "food_order": { ... },
  "order_items": [ ... ]
}
```

#### 2b. Webhook Handler

**File:** `watomation/routers/delivery_hooks.py`

**Endpoint:** `POST /delivery-hooks/restaurant-confirmation-request`

**Handlers by trigger_reason:**

| Trigger Reason | Handler | Action |
|----------------|---------|--------|
| `restaurant_unconfirmed` | `_handle_restaurant_unconfirmed()` | Sends Accept/Decline buttons to restaurant admins |
| `restaurant_accept` | `_handle_restaurant_accept()` | Sends pickup time selection (5/15/25 min) |
| `restaurant_decline` | `_handle_restaurant_decline()` | Updates status to `unassigned` |
| `restaurant_timedout` | `_handle_restaurant_timedout()` | Auto-accepts with default prep time |

#### 2c. WhatsApp Callback Handlers

**File:** `watomation/on_callback_wa_handler.py`

| Callback | Handler | Action |
|----------|---------|--------|
| `/RestaurantOrder-Accept` | `restaurant_order_accept_decline_handler()` | Updates `restaurant_confirmation_status` to `restaurant_accept` |
| `/RestaurantOrder-Decline` | `restaurant_order_accept_decline_handler()` | Updates `restaurant_confirmation_status` to `restaurant_decline` |
| `/PickupTime` | `handle_pickup_time_selection()` | Sets `pickup_time` and updates `status` to `unassigned` |

#### 2d. Confirmation Timeout Job

**File:** `ordelo_datamodels/jobs_n_functions/process_restaurant_confirmation.sql`

**Function:** `process_restaurant_confirmation()`

**Schedule:** Every 5 seconds via pg_cron

**Purpose:** Times out orders where restaurant hasn't selected pickup time

**Logic:**
- Finds orders with `restaurant_confirmation_status` IN (`restaurant_unconfirmed`, `restaurant_accept`) AND `pickup_time` IS NULL
- Checks if time since `dtts` exceeds configured timeout
- Updates `restaurant_confirmation_status` to `restaurant_timedout`
- Triggers webhook for auto-acceptance handling

**Configuration:**
- `{rest_ref}_RESTAURANT_CONFIRMATION_TIMEOUT_TIME` (restaurant-specific)
- `RESTAURANT_CONFIRMATION_TIMEOUT_TIME` (global default: 5 minutes)

---

### Phase 3: Dispatch Creation (`process_delivery` + `job_create_dispatch`)

#### 3a. Delivery Detail Management

**File:** `ordelo_datamodels/jobs_n_functions/process_delivery.sql`

**Function:** `process_delivery()`

**Schedule:** Every 5 seconds via pg_cron (job: `manage_delivery_detail`)

**Purpose:**
- Creates `delivery_detail` records for each vehicle type based on `delivery_option`
- Manages vehicle type iteration when current type times out
- Marks orders as `timedout` when all vehicle types exhausted

**Logic:**
1. For each `unassigned` order in `delivery_summary`
2. Determine next vehicle type by rank from `delivery_option`
3. Insert `delivery_detail` if none exists for that vehicle type
4. If all vehicle types timed out and grace period elapsed → mark `delivery_summary.status = 'timedout'`

**Configuration (timeout resolution order):**
1. `{rest_ref}_DELIVERY_TIMEOUT_TIME` — restaurant-specific timeout (minutes)
2. `DELIVERY_TIMEOUT_TIME` — global fallback (minutes)
3. Hardcoded default: 10 minutes

#### 3b. Dispatch Creation

**File:** `ordelo_datamodels/jobs_n_functions/job_create_dispatch.sql`

**Function:** `job_create_dispatch()`

**Schedule:** Every 5 seconds via pg_cron

**Purpose:**
- Finds available riders for unassigned delivery details
- Creates dispatch records in batches
- Updates detail status when no riders available

**Logic:**
1. For each `unassigned` `delivery_detail`
2. Call `get_available_riders(order_number, town, vehicle_type)` to find eligible riders
3. Insert into `delivery_dispatch` up to `DISPATCH_BATCH_SIZE_{VEHICLE_TYPE}` riders
4. If no riders available → update `delivery_detail.status = 'vehicle_type_timedout'`

**Helper Function:** `get_available_riders(p_order_number, p_town, p_vehicle_type)`
- Returns riders in the specified town with matching vehicle type
- Excludes riders already dispatched for this order
- Excludes riders currently inflight on other deliveries
- Orders by priority

**Configuration:**
- `DISPATCH_BATCH_SIZE_{VEHICLE_TYPE}` (e.g., `DISPATCH_BATCH_SIZE_BICYCLE`)

#### 3c. Dispatch Webhook Trigger

**File:** `ordelo_datamodels/dispatch.sql`

**Trigger:** `trigger_delivery_dispatch_whook`
```sql
AFTER INSERT ON delivery_dispatch
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT
```

**Function:** `delivery_dispatch_whook_statement()`

**Webhook:** POST `/delivery-hooks/delivery-dispatch`

**Payload:**
```json
{
  "bulk_dispatch": [
    {
      "dispatch_id": 123,
      "order_number": "WREN-001",
      "rider_id": "447...",
      "rider_payout": 5.50,
      "vehicle_type": "bicycle",
      "distance": 2.3,
      "pickup_time": "2025-12-10T14:30:00Z",
      "rest_name": "Restaurant Name",
      "rest_address": "...",
      "customer_name": "...",
      "customer_address": "..."
    }
  ]
}
```

**Handler:** `delivery_dispatch_hook()` in `delivery_hooks.py`
- Sends WhatsApp message to each rider with Accept/Decline buttons
- Includes order details, payout, distance, pickup time

---

### Phase 4: Rider Assignment (`job_assign_dispatch`)

#### 4a. Rider Acceptance

**File:** `watomation/on_callback_wa_handler.py`

**Callback:** `/dispatchResponse`

**Handler:** `dispatch_response()`

**Action:**
- Validates dispatch is still available
- Updates `delivery_dispatch.status` to `accepted` or `declined`
- Sends confirmation message to rider

#### 4b. Dispatch Assignment Job

**File:** `ordelo_datamodels/jobs_n_functions/job_assign_dispatch.sql`

**Function:** `job_assign_dispatch()`

**Schedule:** Every 5 seconds via pg_cron

**Purpose:** Assigns first accepted dispatch to the delivery

**Logic:**
1. For each `delivery_detail` with `status` IN (`unassigned`, `vehicle_type_timedout`)
2. Call `assign_accepted_dispatch(order_number)`

**Helper Function:** `assign_accepted_dispatch(p_order_number)`

**Logic:**
1. Find `delivery_dispatch` with `status = 'accepted'` and not already inflight
2. Rank by `dispatch_id`, select first
3. Update `delivery_dispatch.status = 'assigned'`
4. Update `delivery_detail.status = 'assigned'`, set `dispatch_id`, `rider_id`
5. Update `delivery_summary.status = 'assigned'`
6. Insert into `delivery_inflight`

---

### Phase 5: Delivery Execution (Inflight)

#### 5a. Inflight Trigger

**File:** `ordelo_datamodels/inflight.sql`

**Trigger:** `trigger_delivery_inflight_whook`
```sql
AFTER INSERT ON delivery_inflight
FOR EACH ROW
```

**Function:** `delivery_inflight_whook()`

**Webhook:** POST `/delivery-hooks/delivery-inflight-graph-init`

**Payload:**
```json
{
  "delivery_inflight": [ { "dispatch_id": ..., "order_number": ..., "rider_id": ..., "customer_id": ... } ],
  "delivery_summary": { ... },
  "rider_master": { "rider_id": ..., "rider_name": ... }
}
```

**Side Effects:**
1. Calls `notify_missed_dispatches()` to inform other riders who accepted

#### 5b. Graph Initialization Handler

**File:** `watomation/routers/delivery_hooks.py`

**Endpoint:** POST `/delivery-hooks/delivery-inflight-graph-init`

**Handler:** `delivery_inflight_graph_init_hook()`

**Actions (Background Tasks):**
1. `capture_payment()` - Captures Stripe payment
2. `post_rider_event_inflight()` - Notifies restaurant webhook of rider assignment
3. `admin_order_reciept()` - Sends admin notification
4. `init_ordelo_graph()` - Initializes LangGraph rider agent with delivery state
5. `notify_overwatch()` - Logs inflight event to overwatch channel

#### 5c. Missed Dispatches Notification

**File:** `ordelo_datamodels/inflight.sql`

**Function:** `notify_missed_dispatches()`

**Webhook:** POST `/delivery-hooks/notify-missed-dispatches`

**Purpose:** Notifies riders who accepted but weren't assigned that the job was taken

**Handler:** `notify_missed_dispatches_hook()` in `delivery_hooks.py`
- Sends WhatsApp message to each missed rider
- Updates `delivery_dispatch.status = 'missed'`

#### 5d. Rider Agent (LangGraph)

**Files:** `ordelo/agents/rider_agent.py`, `ordelo/agents/agent_runner.py`

The rider agent is a LangGraph `StateGraph` that manages the rider through the entire inflight delivery workflow via WhatsApp.

##### Agent State (`AgentState` TypedDict)

| Field | Type | Description |
|-------|------|-------------|
| `messages` | `Sequence[BaseMessage]` | Conversation history (uses `add_messages` reducer) |
| `rider_name` | `str` | Name of the assigned rider |
| `dispatch_id` | `int` | Active dispatch ID |
| `order_number` | `str` | Order being delivered |
| `reply_to_msg_id` | `str` | WhatsApp message ID for reply threading |
| `start_live_tracking_url` | `str` | OwnTracks config URL for this delivery |
| `delivery_start_dtts` | `str` | ISO timestamp when delivery started |
| `is_restaurant_confirmation_code_verified` | `bool` | Whether restaurant CC has been verified |
| `is_customer_confirmation_code_verified` | `bool` | Whether customer CC has been verified |
| `awaiting_cancel_reason` | `bool` | Whether agent is waiting for rider's cancel reason |

##### Graph Structure

```
START → riderAgent → toolNode → riderAgent → respondNode → END
```

- **`riderAgent`** (`agent_node`): Main decision node. Invokes the LLM-backed rider agent, routes to `toolNode` if a tool call is produced, or to `respondNode` for a plain text reply. Also handles the `awaiting_cancel_reason` shortcut: when the agent is waiting for a cancel reason and the rider replies, it synthesizes a `terminate_delivery_job` tool call with the rider's message as `reason_for_decline`.
- **`toolNode`** (`ToolNode`): Executes tool calls against the 10 registered tools, then returns to `riderAgent`.
- **`respondNode`** (`respond_node`): Sends the final `AIMessage` content to the rider via WhatsApp, then ends the turn.

**Persistence:** `AsyncPostgresSaver` (PostgreSQL checkpointer). Each rider has a LangGraph thread managed via `ThreadHandler`, keyed by recipient phone number.

##### Agent Tools (10 total)

| # | Tool | Arguments | Description |
|---|------|-----------|-------------|
| 1 | `send_delivery_instructions` | *(none)* | Sends pickup/dropoff addresses + live tracking URL to the rider. Sets `reply_to_msg_id` in state. |
| 2 | `send_start_live_tracking_link` | *(none)* | Sends a WhatsApp button-URL message to enable OwnTracks live location tracking. |
| 3 | `notify_food_ready_for_pickup` | `restaurant_name: str` | Notifies the rider that food is ready for pickup at the restaurant and sends the pickup location. |
| 4 | `send_pickup_location` | *(none)* | Re-sends the pickup (restaurant) location to the rider via WhatsApp. |
| 5 | `send_dropoff_location` | *(none)* | Re-sends the dropoff (customer) location to the rider via WhatsApp. |
| 6 | `cancel_delivery_before_pickup` | *(none)* | Cancels an assigned dispatch before pickup. Calls `dispatch_cancel_before_pickup(p_dispatch_id)` RPC to revert statuses. Only allowed when `delivery_dispatch.status = 'assigned'` (before restaurant CC verification marks it `pickedup`). Sets `awaiting_cancel_reason = True`. |
| 7 | `capture_reason_for_cancel_before_pickup` | `reason_for_decline: str` | Persists the rider's cancel reason on `delivery_dispatch.reason_for_decline`. Should be called after tool #6. Sets `awaiting_cancel_reason = False`. |
| 8 | `verify_restaurant_confirmation_code` | `restaurant_confirmation_code: int` | Verifies the 2-digit restaurant code. On success: marks `delivery_dispatch.status = 'pickedup'`, sets `is_restaurant_confirmation_code_verified = True`, and posts a customer notification via `post_rider_event_restaurant_cc`. |
| 9 | `verify_customer_confirmation_code` | `customer_confirmation_code: int` | Verifies the 2-digit customer code. On success: calls `dispatch_complete_func(p_dispatch_id)` RPC, notifies customer and restaurant admins, makes the thread inactive, and sets `is_customer_confirmation_code_verified = True`. |
| 10 | `terminate_delivery_job` | `reason_for_decline: str (optional)` | Closes the delivery job. If `awaiting_cancel_reason` is true and a reason is provided, persists it first. Makes the thread inactive, then sends a stop-tracking button-URL to the rider. |

##### Agent Workflow

The rider agent follows this flow during a normal delivery:

1. **Delivery Instructions** — `init_ordelo_graph()` seeds the graph state (`dispatch_id`, `order_number`, `rider_name`, `start_live_tracking_url`, `delivery_start_dtts`) and invokes the graph. The LLM calls `send_delivery_instructions` to send pickup/dropoff details plus the live tracking link.
2. **Start Live Tracking** — The agent calls `send_start_live_tracking_link` to send the OwnTracks URL via a WhatsApp button.
3. **Pickup Verification** — When the rider provides a 2-digit number, the agent calls `verify_restaurant_confirmation_code`. On success, `delivery_dispatch.status` transitions to `pickedup` and the customer is notified that food has been picked up.
4. **Dropoff Verification** — After delivery, the rider provides the customer confirmation code. The agent calls `verify_customer_confirmation_code`. On success, `dispatch_complete_func` is called (see Phase 6) and the thread is closed.
5. **Job Closure** — The agent calls `terminate_delivery_job` to send the stop-tracking URL and end the conversation.

During the delivery, the rider may request re-sends of pickup/dropoff locations or the tracking link at any time (dynamic detours). The agent handles these and returns to the main flow.

##### Pre-Pickup Cancellation Flow

If the rider indicates they cannot complete pickup **before** restaurant code verification:

1. Agent calls `cancel_delivery_before_pickup` → Supabase RPC `dispatch_cancel_before_pickup(p_dispatch_id)`.
2. RPC sets `delivery_dispatch.status = 'declined'`, deletes the `delivery_inflight` row, and reverts `delivery_detail` + `delivery_summary` to `unassigned`.
3. Agent sets `awaiting_cancel_reason = True` and asks the rider for a reason.
4. When the rider replies, `agent_node` detects `awaiting_cancel_reason` and synthesizes a `terminate_delivery_job` tool call with `reason_for_decline` set to the rider's message.
5. `terminate_delivery_job` persists the reason on `delivery_dispatch.reason_for_decline`, closes the thread, and sends the stop-tracking link.
6. The order is now `unassigned` and eligible for re-dispatch. The cancelled rider already has a `delivery_dispatch` row with `status = 'declined'`, so `get_available_riders()` excludes them from future batches for this order.

##### Graph Initialization (`init_ordelo_graph`)

**File:** `ordelo/agents/agent_runner.py`

Called as a background task from `delivery_inflight_graph_init_hook()`:

1. Creates `ContextSchema` with async pool, WhatsApp client, recipient, and Supabase client.
2. Compiles the graph with `AsyncPostgresSaver` checkpointer.
3. Looks up (or creates) the LangGraph thread for the rider via `get_config_for_recipient()`.
4. Generates the OwnTracks start-tracking URL via `create_start_job_config()`.
5. Seeds state: `dispatch_id`, `order_number`, `start_live_tracking_url`, `delivery_start_dtts`, `rider_name`.
6. Invokes the graph with a system message ("Rider X has accepted the delivery job, call `send_delivery_instructions`") and a human message ("I have accepted the delivery job.").

##### Thread Management

- **Thread-per-rider mapping**: Each rider phone number maps to one active LangGraph thread via `ThreadHandler`. A new thread is created on graph init if no active thread exists.
- **Stale thread cleanup**: `job_terminate_stale_active_threads` (pg_cron) and the `/thread-hooks/terminate-stale-active-threads` endpoint detect threads inactive for >5 minutes and close them via `terminate_delivery_job`.
- **Manual intervention**: The `/thread-hooks/run-system-message` endpoint allows injecting a system message into an active thread (e.g., to trigger a tool call or update state), useful for operational support.

#### 5e. Live Location Tracking

**File:** `ordelo_datamodels/jobs_n_functions/job_null_or_outdated_location.sql`

**Function:** `job_null_or_outdated_location()`

**Schedule:** Periodic via pg_cron

**Purpose:** Identifies inflight deliveries with missing or stale location data

**Webhook:** POST `/location-hooks/null-or-outdated-location`

**Configuration:**
- `LOCATION_ENABLE_TIME_INTERVAL` (minutes before location is considered outdated)

---

### Phase 6: Completion (`dispatch_complete_func`)

**File:** `ordelo_datamodels/jobs_n_functions/dispatch_complete_func.sql`

**Function:** `dispatch_complete_func(p_dispatch_id BIGINT)`

**Invocation:** Called by rider agent after customer confirmation code verification

**Purpose:**
- Marks delivery as completed across all tables
- Cleans up inflight record

**Logic:**
1. Update `delivery_dispatch.status = 'completed'`
2. Update `delivery_detail.status = 'completed'`
3. Update `delivery_summary.status = 'completed'`
4. Delete from `delivery_inflight`

---

## Triggers and Webhooks

| Trigger | Table | Condition | Function | Webhook |
|---------|-------|-----------|----------|---------|
| `trigger_restaurant_updates` | `delivery_summary` | INSERT or UPDATE of `restaurant_confirmation_status` | `restaurant_updates_whook()` | `/delivery-hooks/restaurant-confirmation-request` |
| `trigger_delivery_summary_timedout` | `delivery_summary` | UPDATE `status` to `timedout` | `delivery_summary_timedout_whook()` | `/delivery-hooks/delivery-timedout` |
| `trigger_delivery_dispatch_whook` | `delivery_dispatch` | INSERT (statement-level) | `delivery_dispatch_whook_statement()` | `/delivery-hooks/delivery-dispatch` |
| `trigger_delivery_inflight_whook` | `delivery_inflight` | INSERT | `delivery_inflight_whook()` | `/delivery-hooks/delivery-inflight-graph-init` |

---

## Scheduled Jobs (pg_cron)

| Job Name | Function | Schedule | Purpose |
|----------|----------|----------|---------|
| `manage_delivery_detail` | `process_delivery()` | Every 5s | Create delivery details, handle vehicle type timeouts |
| `create_dispatch_for_unassigned_orders` | `job_create_dispatch()` | Every 5s | Create dispatch records for available riders |
| `assign_delivery_for_accepted_jobs` | `job_assign_dispatch()` | Every 5s | Assign accepted dispatches to deliveries |
| `process_restaurant_confirmation` | `process_restaurant_confirmation()` | Every 5s | Timeout unconfirmed restaurant orders |
| `job_close_thread` | `job_close_thread()` | Every 5 min | Close inactive rider chat threads |
| `job_null_or_outdated_location` | `job_null_or_outdated_location()` | Periodic | Alert on missing live tracking |
| `job_terminate_stale_active_threads` | `job_terminate_stale_active_threads()` | Periodic | Cleanup stale threads |

 Availability enquiry jobs (non-critical workflow support):
 
 - **Shift availability enquiry (riders)**
   - Function: `enquire_shift_availability()`
   - Schedule: Daily via pg_cron (job name is environment-specific)
   - Webhook: `POST /delivery-hooks/shift-availability-enquiry`
   - Payload (simplified):
     ```json
     {
       "event_type": "shift_availability_enquiry",
       "timestamp": 1734212345,
       "riders": [{"rider_id": "447...", "rider_name": "..."}]
     }
     ```
 
 - **Admin availability enquiry (restaurant admins)**
   - Function: `enquire_admin_availability(p_rest_ref_list VARCHAR[] DEFAULT NULL)`
   - Schedule: Daily via pg_cron (job name is environment-specific)
   - Webhook: `POST /delivery-hooks/admin-availability-enquiry`
   - Payload (simplified):
     ```json
     {
       "event_type": "admin_availability_enquiry",
       "timestamp": 1734212345,
       "restaurant_admins": {
         "ELAS": ["447...", "447..."],
         "ORDELO": ["447..."]
       }
     }
     ```
 
 **Timeout note:** These jobs are invoked from the DB and must return quickly. The corresponding FastAPI endpoints acknowledge success immediately and perform WhatsApp fan-out in background tasks.

---

## Status Transitions

### Complete Order Journey

```
1. init_delivery()
   └── delivery_summary.status = 'restaurant_unconfirmed'
       delivery_summary.restaurant_confirmation_status = 'restaurant_unconfirmed'
       └── [Trigger: restaurant_updates_whook → WhatsApp to restaurant]

2. Restaurant Response
   ├── Accept → restaurant_confirmation_status = 'restaurant_accept'
   │   └── [Trigger: WhatsApp pickup time selection]
   │       └── Pickup time selected → status = 'unassigned'
   ├── Decline → restaurant_confirmation_status = 'restaurant_decline'
   │   └── status = 'unassigned' (proceeds without confirmation)
   └── Timeout → restaurant_confirmation_status = 'restaurant_timedout'
       └── status = 'unassigned', auto-accept with default prep time

3. process_delivery()
   └── Creates delivery_detail with status = 'unassigned'

4. job_create_dispatch()
   └── Creates delivery_dispatch with status = 'unassigned'
       └── [Trigger: WhatsApp to riders]

5. Rider Response
   ├── Accept → delivery_dispatch.status = 'accepted'
   ├── Decline → delivery_dispatch.status = 'declined'
   └── No response (30s) → delivery_dispatch.status = 'timedout'

6. job_assign_dispatch() → assign_accepted_dispatch()
   └── delivery_dispatch.status = 'assigned'
       delivery_detail.status = 'assigned'
       delivery_summary.status = 'assigned'
       └── Insert delivery_inflight
           └── [Trigger: Graph init, restaurant webhook, missed dispatch notifications]

7. verify_restaurant_confirmation_code (rider agent)
   └── delivery_dispatch.status = 'pickedup'
       └── [Customer notified: food picked up]

8. verify_customer_confirmation_code → dispatch_complete_func()
   └── delivery_dispatch.status = 'completed'
       delivery_detail.status = 'completed'
       delivery_summary.status = 'completed'
       └── Delete delivery_inflight

8a. (Alternative) cancel_delivery_before_pickup → dispatch_cancel_before_pickup()
    └── delivery_dispatch.status = 'declined'
        delivery_detail.status = 'unassigned' (rider_id/dispatch_id cleared)
        delivery_summary.status = 'unassigned'
        └── Delete delivery_inflight → order re-enters dispatch cycle
```

---

## Configuration Keys

| Key | Default | Description |
|-----|---------|-------------|
| `ORDELO_APP_URL` | `https://rider-agent.ordelo.app` | Base URL for webhook calls |
| `CONFIRMATION_CODE_SALT` | - | Salt for generating confirmation codes |
| `RESTAURANT_CONFIRMATION_TIMEOUT_TIME` | 5 | Minutes before restaurant confirmation times out |
| `{rest_ref}_RESTAURANT_CONFIRMATION_TIMEOUT_TIME` | - | Restaurant-specific timeout override |
| `DELIVERY_TIMEOUT_TIME` | 5 | Minutes before delivery times out (all vehicles exhausted) |
| `{rest_ref}_DELIVERY_TIMEOUT_TIME` | - | Restaurant-specific delivery timeout |
| `PICKUP_DEFAULT_TIME` | 30 | Minutes after order time used as pickup time when restaurant confirmation times out (takeaway only) |
| `{rest_ref}_PICKUP_DEFAULT_TIME` | - | Restaurant-specific override for `PICKUP_DEFAULT_TIME` |
| `DELIVERY_PICKUP_DEFAULT_TIME` | 30 | Minutes after order time used as pickup time when restaurant confirmation times out (delivery orders) |
| `{rest_ref}_DELIVERY_PICKUP_DEFAULT_TIME` | - | Restaurant-specific override for `DELIVERY_PICKUP_DEFAULT_TIME` |
| `DISPATCH_BATCH_SIZE_{VEHICLE_TYPE}` | 1 | Number of riders to dispatch per batch |
| `LOCATION_ENABLE_TIME_INTERVAL` | 1 | Minutes before location is considered outdated |
| `THREAD_INACTIVE_TIME_INTERVAL` | 5 | Minutes of inactivity before thread closure |

---

## Workflow Diagram

```mermaid
flowchart TD
    subgraph Phase1[Phase 1: Order Creation]
        A[External Service] -->|init_delivery| B[delivery_summary]
        B -->|status=restaurant_unconfirmed| C[trigger_restaurant_updates]
    end

    subgraph Phase2[Phase 2: Restaurant Confirmation]
        C -->|webhook| D[/restaurant-confirmation-request]
        D -->|WhatsApp| E[Restaurant Admin]
        E -->|Accept| F[restaurant_accept]
        E -->|Decline| G[restaurant_decline]
        F -->|WhatsApp| H[Pickup Time Selection]
        H -->|Selected| I[status=unassigned]
        G --> I
        J[process_restaurant_confirmation] -->|timeout| K[restaurant_timedout]
        K --> I
    end

    subgraph Phase3[Phase 3: Dispatch Creation]
        I --> L[process_delivery]
        L -->|insert| M[delivery_detail]
        M --> N[job_create_dispatch]
        N -->|insert| O[delivery_dispatch]
        O -->|trigger| P[/delivery-dispatch]
        P -->|WhatsApp| Q[Riders]
    end

    subgraph Phase4[Phase 4: Rider Assignment]
        Q -->|Accept/Decline| R[dispatch_response]
        R -->|status=accepted| S[job_assign_dispatch]
        S -->|assign_accepted_dispatch| T[delivery_inflight]
    end

    subgraph Phase5[Phase 5: Delivery Execution]
        T -->|trigger| U[/delivery-inflight-graph-init]
        U --> V[init_ordelo_graph]
        U --> W[post_rider_event_inflight]
        U --> X[capture_payment]
        T --> Y[notify_missed_dispatches]
        V --> Z[Rider Agent Flow]
    end

    subgraph Phase6[Phase 6: Completion]
        Z -->|customer CC verified| AA[dispatch_complete_func]
        AA -->|status=completed| AB[Delivery Complete]
    end
```

---

## SQL Files Reference

### Core Tables
| File | Description |
|------|-------------|
| `summary.sql` | `delivery_summary` table, `restaurant_updates_whook()`, `delivery_summary_timedout_whook()` triggers |
| `detail.sql` | `delivery_detail` table definition |
| `dispatch.sql` | `delivery_dispatch` table, `delivery_dispatch_whook_statement()` trigger |
| `inflight.sql` | `delivery_inflight` table, `delivery_inflight_whook()` trigger, `notify_missed_dispatches()` |

### Jobs and Functions
| File | Description |
|------|-------------|
| `init_delivery.sql` | Entry point function for new orders |
| `process_delivery.sql` | Manages delivery_detail records and vehicle type iteration |
| `job_create_dispatch.sql` | Creates dispatch records, `get_available_riders()` helper |
| `job_assign_dispatch.sql` | Assigns accepted dispatches, `assign_accepted_dispatch()` helper |
| `dispatch_complete_func.sql` | Marks delivery as completed |
| `dispatch_cancel_before_pickup.sql` | Cancels assigned dispatch before pickup, reverts order to `unassigned` for re-dispatch |
| `process_restaurant_confirmation.sql` | Times out unconfirmed restaurant orders |
| `enquire_shift_availability.sql` | Scheduled rider shift availability enquiry (DB → webhook → WhatsApp template) |
| `enquire_admin_availability.sql` | Scheduled restaurant admin availability enquiry (DB → webhook → WhatsApp template) |
| `job_restaurant_confirmation_timeout.sql` | Alternative timeout handler with auto-accept |
| `job_null_or_outdated_location.sql` | Alerts on missing live tracking |
| `job_close_thread.sql` | Closes inactive rider chat threads |
| `job_terminate_stale_active_threads.sql` | Cleanup stale threads via webhook |
| `cleanupDeliveryOrder.sql` | Testing utility to delete order records |

### Supporting Files
| File | Description |
|------|-------------|
| `ordelo_config.sql` | Configuration key-value store |
| `masterdata.sql` | `restaurant_master`, `customer_master`, `rider_master` tables |
| `location.sql` | `rider_location`, `rider_location_event` tables |
| `delivery_option.sql` | Vehicle type options per order |

---

## FastAPI Webhook Endpoints

| Endpoint | Method | Trigger Source | Handler |
|----------|--------|----------------|---------|
| `/delivery-hooks/restaurant-confirmation-request` | POST | `restaurant_updates_whook()` | `restaurant_confirmation_flow()` |
| `/delivery-hooks/delivery-dispatch` | POST | `delivery_dispatch_whook_statement()` | `delivery_dispatch_hook()` |
| `/delivery-hooks/delivery-inflight-graph-init` | POST | `delivery_inflight_whook()` | `delivery_inflight_graph_init_hook()` |
| `/delivery-hooks/notify-missed-dispatches` | POST | `notify_missed_dispatches()` | `notify_missed_dispatches_hook()` |
| `/delivery-hooks/delivery-timedout` | POST | `delivery_summary_timedout_whook()` | `delivery_timedout()` |
| `/delivery-hooks/shift-availability-enquiry` | POST | `enquire_shift_availability()` | `shift_availability_enquiry_hook()` |
| `/delivery-hooks/admin-availability-enquiry` | POST | `enquire_admin_availability(p_rest_ref_list)` | `admin_availability_enquiry_hook()` |
| `/delivery-hooks/close-threads` | POST | `job_close_thread()` | `close_threads()` |
| `/delivery-hooks/notify-food-ready-for-pickup/{recipient}` | POST | Restaurant admin agent | `notify_food_ready_for_pickup()` |
| `/delivery-hooks/check-rider-allocation-status/{order_number}` | GET | External services | `check_rider_allocation_status()` |
| `/location-hooks/null-or-outdated-location` | POST | `job_null_or_outdated_location()` | Location hooks router |
| `/thread-hooks/run-system-message` | POST | Operational support | `run_system_message()` |
| `/thread-hooks/terminate-stale-active-threads` | POST | `job_terminate_stale_active_threads()` | `terminate_stale_active_threads()` |

---

*End of Delivery Process Documentation*
