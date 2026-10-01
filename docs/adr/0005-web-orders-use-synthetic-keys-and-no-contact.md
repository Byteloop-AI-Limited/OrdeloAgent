# ADR 0005: Web orders use synthetic keys and carry no customer contact

## Status

Accepted (2026-10-01). Plan decisions D9, D10, D24.

## Decision

A web order reuses the existing order tables with synthetic values instead of
new nullable columns:

- its customer key is a **W-id** (`W` + 11 base32 characters), a
  `customer_master` row that holds one checkout's delivery address and uses the
  W-id as `cust_name`, just as WhatsApp orders use the WhatsApp number;
- its `thread_id` is a **web thread** (`WEB-<uuid>`), which correlates the
  checkout, order and payment but never runs an agent.

Web checkout collects **no name and no phone**. No customer contact is stored
for a web order.

## Considered options

- **Make `food_order.thread_id`, `recipient` and the phone-keyed customer
  model optional.** Rejected for launch: it touches the order, summary and
  payment-path code that WhatsApp orders depend on.
- **Collect a phone for web deliveries only** (recommended at the time) or for
  all web orders. Rejected by the owner: today's WhatsApp process never asks
  for one.

## Consequences

- `init_delivery` / `init_takeaway`, pricing and the payment path work
  unchanged with a W-id.
- Anything that treats `customer_id` as a phone must check first. The rider's
  "send customer contact" tool tells the rider no number is on file instead of
  sending the W-id, and restaurant receipts show the W-id.
- No customer can be phoned about a web order; the delivery notes are the only
  contact information. What a rider does when the customer can't be found is
  open (plan Q16).
- Second factors that relied on a phone (order lookup, WhatsApp hand-off
  matching) need another basis (plan Q14, Q15).
- Moving to a surrogate customer id or nullable thread later remains possible
  (plan §4, R5).
