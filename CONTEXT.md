# Ordelo Domain Context

Canonical business vocabulary: [GLOSSARY.md](GLOSSARY.md). Communication implementation and outcome semantics: [alerts and notifications](docs/alerts-and-notifications.md).

## Configured auto-accept

A restaurant-level policy stored as `restaurant_master.auto_accept`. When true,
new delivery and takeaway summaries receive a configured pickup time at creation
and bypass manual restaurant confirmation.

## Timeout auto-accept

The default outcome when a manually confirmed order reaches the restaurant-confirmation timeout
(`{REF}_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION` absent or not `decline`): `restaurant_timedout`, then
auto-accepted with the default pickup time. It is not a configured auto-accept order, which never asks the
restaurant at all. An order an admin accepted but gave no pickup time is always timeout auto-accepted, 15 seconds after the accept
(a fixed grace in `process_restaurant_confirmation()`, not a config key), never later than the usual timeout.

## Timeout action

`{REF}_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION`: what silence means for one restaurant, `accept` (default) or
`decline`. Read only through `restaurant_confirmation_policy(rest_ref)`, together with the timeout minutes.

## Timeout auto-decline

The outcome for a never-answered order when the timeout action is `decline`: `restaurant_confirmation_status =
'auto_decline'` and `status = 'declined'`, set together by `process_restaurant_confirmation()`. The customer is
told and the payment cancelled as for an admin decline; admins and ops are told that nobody answered. The web
order page shows a countdown to the deadline for these restaurants.

## Configured-auto order

An order created while configured auto-accept is enabled. It stores
`rest_confirmation_method='configured_auto'`, which keeps later notification
policy deterministic even if restaurant configuration changes.

## Order-card reminders

The repeat sends of an order card (default offsets `0,15,30,45` seconds, `TGRAM_ORDER_ALERT_OFFSETS_SECS`,
overridable per restaurant with `<REF>_TGRAM_ORDER_ALERT_OFFSETS_SECS`; a blank restaurant value falls back to the global one, use `0` for a single card) exist so an admin cannot miss an
order that is waiting for an answer. They are scheduled only for orders whose
`restaurant_confirmation_status` is `restaurant_unconfirmed`, and cancelled as soon as the order is decided on any channel.
So a *configured auto-accept* order (created already accepted) never gets reminders, only a single "auto accepted"
notice and card. A *timeout auto-accept* order is unconfirmed while it waits, so it does get reminders until it is
decided or times out. Reminders are about unanswered orders, not about restaurants that decline.

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
(`ordelo_datamodels/dispatch/job_rider_pickup_alerts.sql`); the FastAPI
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
Business terms are defined in the [canonical glossary](GLOSSARY.md). The [payment implementation reference](docs/glossary.md) maps them to service fields.

### Storefront

Ordelo and direct storefronts use different branding, offers and commission. The choice is fixed at order creation.

### Origin channel

The order retains its original channel when an order page link is opened or a subscription changes.

### Web order

Web orders use manual capture. See [ADR 0003](docs/adr/0003-web-orders-never-reach-restaurant-apps.md) for customer-facing callback routing.

### Order page link (WhatsApp)

OrdeloAgent issues a private `/o/<token>` link when the restaurant app builds the payment receipt. The receipt carries the Order Tracking button. The raw token is omitted from storage.

### Restaurant app

The customer-facing WhatsApp service lives in the sibling restaurant-agents repository.

### Customer key

WhatsApp orders use the WhatsApp number. Checkout starts with a draft web key and order creation mints a separate key whose record preserves the delivery address.

### Web customer key

See [the synthetic key decision](docs/adr/0005-web-orders-use-synthetic-keys-and-no-contact.md).

### Web thread

The record that ties one web checkout attempt to its order and payment. It
lives alongside conversations but is not one: no agent ever runs on it.

### Customer contact

Web checkout does not collect a customer messaging destination. Delivery address data is stored separately from messaging contact.

### Capture point

Delivery capture is scheduled by the assignment webhook. Collection capture follows the first scheduled pickup time.

### Payment release

See [the payment flow](docs/payment_and_order_flow.md) for release handling.

### Payment-complete event

Stripe's notice that a customer has authorised payment for an order. Ordelo
receives it straight from Stripe, unsigned, and applies it at most once per
order.

### Post-payment redirect

Where Stripe sends the customer's browser after paying or cancelling. Fixed per
restaurant, not per order.
The frontend has a payment-return view, but the provider's configured redirect
is a separate contract; the existence of that view does not prove it is used.

### Customer event

A change in an order that the customer cares about, such as "rider assigned" or
"ready for collection". Recorded once per order and event key, however many places it is
later presented or communicated to. Different pickup times can have different keys.

### Notification subscription

A standing instruction to send one order's customer events to one destination
at one detail level. An order's origin channel and its subscriptions are
independent of each other.

### Customer notifier

The main boundary that records customer events and routes subscription updates.
Web subscribers read the order page; WhatsApp subscribers invoke their restaurant
app. It is not the owner of every operational message. The current WhatsApp
collection-decline handler remains a direct-send exception.

### Detail level

The order view projects `full`, `recovered` or `status_only` under [ADR 0016](docs/adr/0016-orders-are-found-by-postcode-and-unlocked-by-house.md).

### Order access grant

The browser presents an order-bound token. The grant determines the detail level. See [order access](utils_common/web_ordering/order_access.py).

### Hand-off code

See the [canonical glossary](GLOSSARY.md#acceptance-identity-and-checkout) for the intended hand-off. Check current route support before describing it as an active workflow.

### Restaurant-admin bot

The Telegram bot (`bot_key` `rest_admin`) restaurant admins use for order
actions and notifications alongside WhatsApp. It is deterministic and never
runs a LangGraph agent. It is not a customer channel.

### Admin roster

The restaurant admins Ordelo knows: one entry per person per restaurant, keyed by the person's phone number. Membership
comes only from each restaurant's own admin list, which is authoritative; a person may be on several restaurants' lists
and is an admin only while on at least one. Being on the roster is what makes someone a restaurant admin; every
channel's reach and every admin action is checked against it. Only an operator adds people to a restaurant's list.

### Admin record

One restaurant admin as a person, keyed by phone and shared by every restaurant they are on: their Telegram link,
whether their phone is verified, their name and how they want to be reached. It confers no authority by itself; a record
whose phone is on no restaurant's admin list belongs to nobody's roster and receives nothing.

### Admin link

The binding of one Telegram account to one admin record. It is created only by the person sharing their own phone
number through the restaurant bot, and only when that number is on at least one restaurant's admin list; an unknown
number is refused and ops is told. It covers every restaurant the person is on.

### Admin channels

Where Ordelo's messages reach one restaurant admin: WhatsApp, Telegram or both, never none. It belongs to the admin
record, so it is the same for every restaurant they are on. An admin with no Telegram link is on WhatsApp only;
linking Telegram moves them to Telegram only (WhatsApp stops), and an operator can change it later. It decides where messages go,
not what the admin may do: a linked admin may act from Telegram whatever their channels are.

### Telegram invite

Being retired: admin links replace it at a single cut-over, with no carry-over of claimed invites.

A single-use, expiring link the operator sends privately so one restaurant
admin can link their Telegram account to one restaurant (`t_invites`: phone
number, restaurant, generated code). The person confirms in the bot; the first
confirmation wins. `phone_verified` is reserved for a later contact-share flow.

### Restaurant decision

An admin's Accept or Decline of an order, and the pickup time chosen after an accept,
recorded by one database function per step (`restaurant_order_decide`,
`restaurant_order_set_pickup`) that every channel uses. The first decision wins; a later
tap is told who decided. A decline is terminal: the delivery order's status becomes
`declined` in the same update, so it can never be dispatched.

### Telegram inbox

The `t_inbox` table: one row per selected consequential Telegram update the bot has
claimed, keyed by `(bot_key, update_id)`. Protected handlers claim before doing their
work; a retry of that update is skipped (at-most-once). Read-only, fallback and
unmatched updates have no inbox row. `tuid` is the sender's Telegram user id.

### Order card

The Telegram message an admin sees for one order: a status line, the order number, total,
type and items, and Accept / Decline or pickup-time buttons. It is an immutable value
changed only by events (reminded, accepted, declined, pickup chosen, auto-accepted,
vanished) and always rebuilt from the order in the database, so it can never show a state
the database is not in. Each admin's chat holds at most one live copy; the `t_sent_messages`
ledger only remembers where copies are so they can be edited or deleted.
The buttons are authorised per tap by Telegram user id (never chat id), so the same card works in a private chat or a group.
A delivery card with a pickup time carries the hold lines; the kitchen receipt is the start signal.

### Kitchen instruction

What the kitchen is told about an accepted order: **hold** (delivery, from the pickup time until the kitchen receipt arrives following assignment),
**start** (the kitchen receipt), or **drop** (no rider found: the order is cancelled and must not be prepared).
Takeaway is never held. The plain wording and UK pickup time live in
`utils_common/order_management/kitchen_instructions.py`; each channel adds its own markup.
The delivery order card stays terminal; a receipt threaded beneath it supersedes the hold (ADR 0015).

### Telegram identity

A Telegram user ID identifies the actor and a chat ID addresses messages. Admin authority is checked against the roster. Invite-based identity is the legacy path.

## Riders on Telegram

### Rider link

The binding of one Telegram account to one rider, stored on the rider row (Telegram user id authorises, chat id
addresses). It is created only by the rider sharing their own phone number through the bot, never from typed text, and
moves to a new account when that account proves the same number.

### Rider channel

Where the messages Ordelo starts reach a rider: WhatsApp or Telegram, one at a time. A dispatch keeps the channel it
was offered on until the job ends, so a job conversation never moves between apps.

### Rider thread

[ADR 0012](docs/adr/0012-rider-threads-follow-dispatch-assignments.md) describes dispatch-based IDs, legacy lookups, and the lifetime of cancellation aftercare.

### Offer

**Offer reminder**: A repeat of an unanswered Telegram offer at configured offsets, replacing the previous copy. Stops when any rider accepts or this rider can no longer take it. A decline restarts nothing; cancellation before pickup re-offers the order and starts a complete new cycle. Overwatch is told once per dispatch round. Avoid: nag, re-dispatch (a re-dispatch is a new offer).

One delivery job proposed to one rider (one dispatch row) with Accept and Decline. When the job goes to someone else,
expires or is cancelled, the offer is closed: on Telegram it is edited in place and loses its buttons.

### Job card

The message a rider gets once a job is theirs: pickup time, restaurant, earning, distance, and three buttons (Pickup
Location, Dropoff Location, Contact Customer). A button tap reaches the rider agent as the rider's own words, so both apps
behave the same.

### Pause

[ADR 0013](docs/adr/0013-pauses-have-a-mandatory-end-and-are-computed.md) describes clock-based expiry and the routing changes for admin alerts.

### Last-admin guard

A restaurant admin cannot pause alerts if no other admin of that restaurant would stay unpaused, so a restaurant always has someone receiving its new Telegram order alerts.


**Cancel confirmation**: Before pickup, a rider must tap a channel button before cancellation; the callback carries a token and is marked as a trusted tap in the agent input.

**Post-pickup refusal**: The agent refuses rider requests to cancel or close after pickup and alerts overwatch for each attempt. Database concurrency still needs a lock to guarantee this during simultaneous pickup and cancellation.

## Order recovery (ADR 0016)

The lookup query reads `web_order_request.lookup_postcode`. Unlock uses `web_house_key()`, which normalizes the saved house number or name and excludes a flat on its own. See the [glossary](GLOSSARY.md#identity-access-and-tracking) and [ADR 0016](docs/adr/0016-orders-are-found-by-postcode-and-unlocked-by-house.md).
