# Ordelo Domain Context

## Configured auto-accept

A restaurant-level policy stored as `restaurant_master.auto_accept`. When true,
new delivery and takeaway summaries receive a configured pickup time at creation
and bypass manual restaurant confirmation.

## Timeout auto-accept

The existing fallback for an otherwise manually confirmed order that reaches the
restaurant-confirmation timeout. It shares `restaurant_confirmation_status` of
`auto_accept` but is not a configured auto-accept order.

## Configured-auto order

An order created while configured auto-accept is enabled. It stores
`rest_confirmation_method='configured_auto'`, which keeps later notification
policy deterministic even if restaurant configuration changes.

## Delivery progress

The answer to "is this delivery still in progress, and has the food been
collected?", read straight from the delivery tables rather than agent/graph
state (which goes blind once a thread closes). Resolved by
`ordelo.delivery_progress.check_delivery_progress()` as one of:

- **Not in progress** - no `delivery_inflight` row for the order (completed,
  cancelled pre-pickup, or a stale WhatsApp button naming a job the rider has
  since moved past).
- **Picked up** - `delivery_inflight` exists and its `delivery_dispatch.status`
  is `pickedup` or `completed`.
- **Awaiting pickup** - `delivery_inflight` exists and dispatch status is
  earlier than `pickedup`. The only state in which an admin action (adjust
  pickup time, notify food ready) should proceed.
- **Unknown** - the read itself failed. Treated as a block, not a pass,
  because WhatsApp buttons never expire and a stale tap must not act on
  unverified state.

Exists because admin receipt buttons (adjust pickup time, "Ready - Notify
Rider") stay tappable indefinitely; without this check a tap on a finished
order could re-fire `trigger_restaurant_updates` or nudge a rider about a job
they finished yesterday.

## Pickup alert

A reminder sent to a rider at a **checkpoint** around the order's
`pickup_time`, so a forgotten pickup or a slow delivery is chased rather than
discovered late.

- **Alert offset** - a signed number of minutes relative to `pickup_time`.
  Negative is *before* pickup (`-15` = fifteen minutes to go), positive is
  *after* (`5` = five minutes late).
- **Checkpoint** - one offset applied to one dispatch in one phase,
  materialised as a row in `rider_pickup_alert` with the moment it comes due
  and whether it has fired (`pending` / `sent` / `superseded`).
- **Phase** - which leg of the job the alert chases. The two phases are named
  for the `DeliveryProgress` values they require, so the SQL gate and the
  Python gate are the same concept:
  - `awaiting_pickup` - dispatch is `assigned`, rider has not collected.
  - `picked_up` - dispatch is `pickedup`, rider is carrying the food but has
    not delivered.
- **Audience** - who hears about it. `rider` alerts run through the rider agent
  so the thread stays faithful; `ops` alerts go to the overwatch list and the
  restaurant's admins by direct WhatsApp send, and never reach the rider - so
  the "everything through the agent" rule does not apply to them.

Phase x audience gives four buckets, each with its own `ordelo_config` key and
its own kill switch:

| Audience | Phase | Config key | Default |
|---|---|---|---|
| `rider` | `awaiting_pickup` | `ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS` | `-15,-5,2,5,7` |
| `rider` | `picked_up` | `ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS` | `30,45` |
| `ops` | `awaiting_pickup` | `rider_alert_to_overwatch_pickup_intervals` | `10` |
| `ops` | `picked_up` | `rider_alert_to_overwatch_delivery_intervals` | `30` |

The two ops buckets are the escalation path: ops hears once when nobody has
collected 10 minutes past the pickup time, and once when a collected order is
still undelivered 30 minutes past it. An order the rider never collects
escalates at `+10` and then goes quiet, because the second point requires
collection.

**All four buckets share one anchor**, `pickup_time` - the post-collection
checkpoints are *not* measured from the moment of collection. So a rider who
collects very late finds those checkpoints already passed and gets one
immediate "you are well past pickup" nudge rather than a fresh ladder.

Scheduling is entirely in `job_rider_pickup_alerts()`
(`ordelo_datamodels/migrations/add_rider_pickup_alerts.sql`); the FastAPI
endpoint is only called when a checkpoint is actually due. When several are due
at once - a cron outage, or a rider who collected long after the pickup time - only
the **largest** fires and the rest are marked `superseded`, because the largest
is the most-recently-passed checkpoint and therefore the truest description of
now. That collapse happens **per audience**, so a rider alert and an ops
escalation can fire on the same tick without suppressing each other. Alert
wording is derived from the real time to pickup, never from the offset that
triggered it.

The ledger lives in a delivery table rather than the rider's LangGraph state for
the same reason "Delivery progress" reads the delivery tables: graph state reads
back `NULL` once a thread goes inactive, which is indistinguishable from
"nothing sent" and would replay the whole sequence. Which reminders have been
sent is the scheduler's bookkeeping, not something the agent needs to believe.
