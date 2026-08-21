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
