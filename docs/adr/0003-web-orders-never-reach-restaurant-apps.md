# ADR 0003: Web orders never reach restaurant apps

## Status

Accepted (2026-10-01). Plan decision D27.

## Decision

Ordelo never sends a web order to a restaurant-agents app. The restaurant-app
calls that exist today (`payment-complete`, rider events, pickup-time updates,
address updates and the rest of the 10 hooks listed in the plan, §2.2) are made
only for WhatsApp orders. Customer updates for web orders go through Ordelo's
customer notifier to the web order page (and, later, to the Ordelo WhatsApp
app).

Restaurant apps are conversations with one restaurant's WhatsApp customers.
They key everything by the customer's WhatsApp number and thread, and a web
order has neither. Sending one would at best fail, and at worst create graph
state for a "customer" who never wrote or attempt WhatsApp messages to a
synthetic key.

## Considered options

- **Let restaurant apps accept web orders and ignore them.** Rejected: it needs
  the same guard in all three apps for every hook, instead of one check in
  Ordelo, and any app that misses one misbehaves.

## Consequences

- `payment_hooks.payment_complete_path` branches on `food_order.origin_channel`:
  WhatsApp orders keep today's restaurant-app call; web orders skip it.
- The restaurant itself still sees web orders through the existing admin
  WhatsApp flows (confirmation, receipts), because those run from Ordelo.
- If a restaurant app ever needs to know about web orders (for example a
  kitchen ticket), that is a new, separate event, not the customer
  conversation's `payment-complete`.
