# Delivery Process Design

This document outlines the end-to-end delivery workflow implemented at the database level using PostgreSQL functions, scheduled jobs, CTEs, and webhooks.

---

## 1. Components & Files

| File                                    | Responsibility                                         |
| --------------------------------------- | ------------------------------------------------------ |
| `create_delivery_detail.sql`            | Insert a new delivery request into `delivery_detail`   |
| `job_create_dispatch.sql`               | Batch-create dispatches for unassigned deliveries      |
| `get_available_riders` (in same file)   | Retrieve up to 5 eligible riders per order             |
| `job_assign_delivery.sql`               | Trigger assignment logic for accepted dispatches       |
| `assign_accepted_dispatch.sql`          | Assign first accepted dispatch & create `inflight`     |
| `notify_missed_dispatches.sql`          | Notify riders of missed dispatches via HTTP webhook    |
| `dispatch_complete_func.sql`            | Finalize a delivery and clean up inflight records      |

---

## 2. Sequence of Events

### 2.1 Delivery Request Creation
- **Invocation**: External app calls `insert_delivery_detail(p_cust_id, p_order_number, p_vehicle_type)`.
- **Purpose**: Fetch restaurant & customer info, compute distance & payout, insert into `delivery_detail`.
- **Logic**:
  1. Derive `rest_ref` from `p_order_number`.
  2. Query `delivery_option` for `p_vehicle_type` → `driver_payout`, `distance_miles`.
  3. Query `restaurant_master` & `customer_master` for geo & address data.
  4. `INSERT` into `delivery_detail` with `status = 'unassigned'`, `dispatch_id=NULL`, `rider_id=NULL`.

### 2.2 Dispatch Creation
- **Invocation**: `job_create_dispatch()` via pg_cron (every 5–10s).
- **Purpose**: Find `unassigned` orders, notify a batch of up to 5 riders, handle timeouts.
- **Logic** (CTEs):
  1. **availableRiders**: JOIN `delivery_detail` ➔ lateral call to `get_available_riders()` to exclude past dispatches/inflight.
  2. **dispatch_insert**: `INSERT INTO delivery_dispatch` for riders (limit 5) with `status='unassigned'`.
  3. **Update `delivery_detail`**: Mark as `timedout` if no riders after 30 min.
- **Side Effects**:
  - DB trigger on `delivery_dispatch` insert 1 but: HTTP POST to `/delivery-hooks/delivery-dispatch`.
  - WhatsApp notifications to riders.

### 2.3 Rider Acceptance
- **Invocation**: Rider clicks acceptance link → API updates `delivery_dispatch.status = 'accepted'`.

### 2.4 Dispatch Assignment
- **Invocation**: `job_assign_delivery()` via pg_cron (every 5s).
- **Purpose**: Assign the first accepted dispatch to the delivery.
- **Logic**:
  1. For each `delivery_detail` with `status='unassigned'`, call `assign_accepted_dispatch(order_number)`.

#### `assign_accepted_dispatch(p_order_number)`
1. **acceptedDispatches**: SELECT from `delivery_dispatch` WHERE `status='accepted'` & not in `delivery_inflight`.
2. **rank** by `dispatch_id`, pick rank=1.
3. **updateDispatch**: `UPDATE delivery_dispatch.status='assigned'`, set timestamp.
4. **updateDetail**: `UPDATE delivery_detail.status='assigned'`, set `dispatch_id`, `rider_id`.
5. **insertInflight**: `INSERT INTO delivery_inflight` record.

### 2.5 Notify Missed Dispatches
- **Invocation**: After assignment, trigger `notify_missed_dispatches_for_order(p_order_number)` or batch `notify_missed_dispatches()`.
- **Purpose**: Inform riders (who accepted but were not assigned) that the job is taken.
- **Logic** (CTE `missed_dispatches`):
  - SELECT accepted dispatches where `delivery_detail.status='assigned'`.
  - Build JSON payload `{ missed_dispatches: [...] }`.
  - HTTP POST to `/delivery-hooks/notify-missed-dispatches`.

### 2.6 Delivery Completion
- **Invocation**: Agent/API calls `dispatch_complete_func(p_dispatch_id)`.
- **Purpose**: Mark delivery as complete and clean up inflight.
- **Logic**:
  1. `UPDATE delivery_dispatch SET status='completed'`.
  2. `UPDATE delivery_detail SET status='completed'`.
  3. `DELETE FROM delivery_inflight WHERE dispatch_id = p_dispatch_id`.

---

## 3. Tables Involved

- **delivery_detail**: Tracks each delivery request and its status.
- **delivery_dispatch**: Records offers sent to riders.
- **delivery_inflight**: Active assignments in progress.
- **restaurant_master**, **customer_master**, **delivery_option**, **rider_master**: Master data lookups.

---

## 4. Scheduling & Triggers

- **pg_cron Jobs**:
  - `create_dispatch_for_unassigned_orders` → `job_create_dispatch()`
  - `assign_delivery_for_accepted_jobs` → `job_assign_delivery()`

- **DB Triggers**:
  - On `delivery_dispatch` INSERT → HTTP webhook `/delivery-hooks/delivery-dispatch`.
  - On status change or via functions → `/notify-missed-dispatches`.

---

*End of design document.*
