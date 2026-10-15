# Ordelo Domain Context

Canonical business vocabulary: [GLOSSARY.md](GLOSSARY.md). Communication implementation and outcome semantics: [alerts and notifications](docs/alerts-and-notifications.md).

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

The legacy implementation name for a **rider timing alert**. A checkpoint can
remind the rider, notify restaurant admins, or escalate to overwatch around the
order's `pickup_time`; it is not restricted to riders or the pickup phase.

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

### Order page link (WhatsApp)

The private `/o/<token>` URL that opens the order page for a paid WhatsApp
order. Minted by OrdeloAgent when the restaurant app builds the payment
receipt, sent once as the receipt's last line, and never stored raw.
_Avoid_: tracking link (on its own), magic link

### Restaurant app

A restaurant-agents WhatsApp app that serves one restaurant's own customers.
It only ever hears about WhatsApp orders.
_Avoid_: customer agent, restaurant agent

### Customer key

The identifier for the customer on an order: the WhatsApp number for a
WhatsApp order, a web customer key for a web order.
_Avoid_: recipient, phone (it is not always one)

### Web customer key

A synthetic customer key (a "W-id") that cannot be used to contact a person.
The checkout has a draft key; creating an order mints a distinct per-order key
whose customer row preserves the delivery address.
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
The frontend has a payment-return view, but the provider's configured redirect
is a separate contract; the existence of that view does not prove it is used.
_Avoid_: treating browser navigation as payment confirmation

### Customer event

A change in an order that the customer cares about, such as "rider assigned" or
"ready for collection". Recorded once per order and event key, however many places it is
later presented or communicated to. Different pickup times can have different keys.
_Avoid_: notification, status update

### Notification subscription

A standing instruction to send one order's customer events to one destination
at one detail level. An order's origin channel and its subscriptions are
independent of each other.
_Avoid_: opt-in (that is the consent), channel

### Customer notifier

The main boundary that records customer events and routes subscription updates.
Web subscribers read the order page; WhatsApp subscribers invoke their restaurant
app. It is not the owner of every operational message. The current WhatsApp
collection-decline handler remains a direct-send exception.
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

### Restaurant-admin bot

The Telegram bot (`bot_key` `rest_admin`) restaurant admins use for order
actions and notifications alongside WhatsApp. It is deterministic and never
runs a LangGraph agent. It is not a customer channel.
_Avoid_: restaurant agent, restaurant chatbot

### Telegram invite

A single-use, expiring link the operator sends privately so one restaurant
admin can link their Telegram account to one restaurant (`t_invites`: phone
number, restaurant, generated code). The person confirms in the bot; the first
confirmation wins. `phone_verified` is reserved for a later contact-share flow.
_Avoid_: invite token, signup link

### Restaurant decision

An admin's Accept or Decline of an order, and the pickup time chosen after an accept,
recorded by one database function per step (`restaurant_order_decide`,
`restaurant_order_set_pickup`) that every channel uses. The first decision wins; a later
tap is told who decided. A decline is terminal: the delivery order's status becomes
`declined` in the same update, so it can never be dispatched.
_Avoid_: confirmation update, order status update

### Telegram inbox

The `t_inbox` table: one row per Telegram update the bot has started to handle,
keyed by `(bot_key, update_id)`. Claiming a row is the first thing the bot does with an
update, so a Telegram retry of the same update is skipped (at-most-once). `tuid` is the
sender's Telegram user id.
_Avoid_: message queue, update log

### Order card

The Telegram message an admin sees for one order: a status line, the order number, total,
type and items, and Accept / Decline or pickup-time buttons. It is an immutable value
changed only by events (reminded, accepted, declined, pickup chosen, auto-accepted,
vanished) and always rebuilt from the order in the database, so it can never show a state
the database is not in. Each admin's chat holds at most one live copy; the `t_sent_messages`
ledger only remembers where copies are so they can be edited or deleted.
The buttons are authorised per tap by Telegram user id (never chat id), so the same card works in a private chat or a group.
_Avoid_: notification, alert message

### Telegram identity

The link from a Telegram account (user id and chat id) to a restaurant, created
when an invite is claimed. It only authenticates: it can be revoked at any time
by setting the invite's status, and a chat id or button payload alone
authorizes nothing.
_Avoid_: Telegram login, Telegram user
