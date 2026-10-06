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
  so the thread stays faithful; `ops` alerts go to the overwatch list, and
  `rest_admins` alerts go to the restaurant's admins - both of the latter by
  direct WhatsApp send, never reaching the rider, so the "everything through
  the agent" rule does not apply to them.

Phase x audience gives six buckets, each with its own `ordelo_config` key and
its own kill switch:

| Audience | Phase | Config key | Default |
|---|---|---|---|
| `rider` | `awaiting_pickup` | `ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS` | `-15,-5,2,5,7` |
| `rider` | `picked_up` | `ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS` | `30,45` |
| `ops` | `awaiting_pickup` | `rider_alert_to_overwatch_pickup_intervals` | `10` |
| `ops` | `picked_up` | `rider_alert_to_overwatch_delivery_intervals` | `30` |
| `rest_admins` | `awaiting_pickup` | `rider_alert_to_rest_admins_pickup_intervals` | `-10,2,7` |
| `rest_admins` | `picked_up` | `rider_alert_to_rest_admins_delivery_intervals` | *(blank = off)* |

The two ops buckets are the escalation path: ops hears once when nobody has
collected 10 minutes past the pickup time, and once when a collected order is
still undelivered 30 minutes past it. An order the rider never collects
escalates at `+10` and then goes quiet, because the second point requires
collection.

The two `rest_admins` buckets are a separate, restaurant-facing schedule with
its own wording (no 🚨 siren): a heads-up at `-10` so the kitchen has the
order ready, then chases at `+2`/`+7`. The `picked_up` bucket ships with a
**blank** default - wired end to end but inactive until someone sets it, since
a "still not delivered" nudge to the restaurant is judged less useful than one
to ops or the rider.

**All six buckets share one anchor**, `pickup_time` - the post-collection
checkpoints are *not* measured from the moment of collection. So a rider who
collects very late finds those checkpoints already passed and gets one
immediate "you are well past pickup" nudge rather than a fresh ladder.

Scheduling is entirely in `job_rider_pickup_alerts()`
(`ordelo_datamodels/jobs_n_functions/job_rider_pickup_alerts.sql`); the FastAPI
endpoint is only called when a checkpoint is actually due. When several are due
at once - a cron outage, or a rider who collected long after the pickup time - only
the **largest** fires and the rest are marked `superseded`, because the largest
is the most-recently-passed checkpoint and therefore the truest description of
now. That collapse happens **per audience**, so a rider alert, an ops
escalation, and a rest_admins message can all fire on the same tick without
suppressing each other - even when two of them share the same offset. Alert
wording is derived from the real time to pickup, never from the offset that
triggered it.

The ledger lives in a delivery table rather than the rider's LangGraph state for
the same reason "Delivery progress" reads the delivery tables: graph state reads
back `NULL` once a thread goes inactive, which is indistinguishable from
"nothing sent" and would replay the whole sequence. Which reminders have been
sent is the scheduler's bookkeeping, not something the agent needs to believe.

## Web ordering

Terms introduced by the web ordering plan (`plans/ordelo-agg-plan-cc.md`).
Payment terms such as authorisation, capture and pickup-time boundary are in
`docs/glossary.md`.

### Storefront

Who sells an order and on whose terms (branding, offers, commission):
**Ordelo** (the aggregator) or **direct** (a restaurant's own customers).
Fixed when the order is created.
_Avoid_: brand, site, shop

### Origin channel

How an order was placed: **WhatsApp** or **web**. Fixed for the order's life;
following the order somewhere else later never changes it.
_Avoid_: channel (on its own), source

### Web order

An order whose origin channel is web. Always paid online with manual capture,
and never sent to a restaurant app.
_Avoid_: online order, site order

### Restaurant app

A restaurant-agents WhatsApp app that serves one restaurant's own customers.
It only ever hears about WhatsApp orders.
_Avoid_: customer agent, restaurant agent

### Customer key

The identifier for the customer on an order: the WhatsApp number for a
WhatsApp order, a web customer key for a web order.
_Avoid_: recipient, phone (it is not always one)

### Web customer key

A synthetic customer key (a "W-id") minted for one web checkout. It holds that
checkout's delivery address and nothing else; it is not a phone number, and no
one can be contacted through it.
_Avoid_: guest id, web user, account

### Web thread

The record that ties one web checkout attempt to its order and payment. It
lives alongside conversations but is not one: no agent ever runs on it.
_Avoid_: web session, checkout session (Stripe's term), conversation

### Customer contact

A way to reach the person who placed an order. A WhatsApp order has one, its
WhatsApp number; a web order has none.
_Avoid_: contact details

### Capture point

The moment an authorised payment is charged: when a rider accepts the delivery
job, or at the pickup-time boundary for collection. Never at checkout for a web
order.
_Avoid_: payment time

### Payment release

Cancelling an authorisation before capture, so the customer is never charged.
_Avoid_: refund (a refund returns money after capture)

### Payment-complete event

Stripe's notice that a customer has authorised payment for an order. Ordelo
receives it straight from Stripe, unsigned, and applies it at most once per
order.
_Avoid_: payment forward, payment webhook (the payment service has its own)

### Post-payment redirect

Where Stripe sends the customer's browser after paying or cancelling. Fixed per
restaurant, not per order.
_Avoid_: return page (a planned Ordelo page that does not exist yet), success page

### Customer event

A change in an order that the customer cares about, such as "rider assigned" or
"ready for collection". Recorded once per order, however many places it is
later delivered to.
_Avoid_: notification, status update

### Notification subscription

A standing instruction to send one order's customer events to one destination
at one detail level. An order's origin channel and its subscriptions are
independent of each other.
_Avoid_: opt-in (that is the consent), channel

### Customer notifier

The one place in Ordelo that turns customer events into messages for each
notification subscription. Nothing else sends order updates to customers.
_Avoid_: messenger, hook caller

### Detail level

How much of an order a viewer or subscriber may see: **full** (address, items,
charges, customer confirmation code) or **status only**.
_Avoid_: access level, permission

### Order access grant

The secret that lets one browser see one order in full. The order number on its
own grants nothing.
_Avoid_: order token, login

### Hand-off code

A one-time code that links a WhatsApp sender to a web order so they can follow
it on WhatsApp.
_Avoid_: OTP, verification code
