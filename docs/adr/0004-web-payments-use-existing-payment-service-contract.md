# ADR 0004: Web payments use the existing payment-service contract

## Status

Accepted (2026-10-01). Plan decisions D22, D23, D25, D26.

## Decision

Web orders call the payment service exactly as WhatsApp orders do: the same
create, capture and cancel requests, manual capture only, with the web thread in
the `thread_id` path segment. The payment service is not changed or redeployed
for web ordering. Everything web-specific about payment lives in Ordelo,
chiefly in `payment_hooks.payment_complete_path`, which Stripe calls directly
and which branches on the order's origin channel.

Ordelo keeps accepting that Stripe event without signature verification, as it
does today: no webhook signing secret is configured in Ordelo or the payment
service. Repeated or out-of-order events are made harmless in Ordelo by an
event log and a conditional status update.

The owner chose this to keep the change inside the one service Ordelo fully
controls.

## Considered options

- **Extend the payment-service request** with per-order success/cancel URLs, a
  session expiry, an idempotency key, customer-detail collection and a signed
  forward to Ordelo. Rejected: too much surface area across two services for
  the first web release.
- **Verify Stripe's signature in Ordelo.** Not adopted for now; it remains an
  Ordelo-only change if revisited, because Stripe issues a signing secret for
  every webhook endpoint.

## Consequences

- **Post-payment redirect gap.** Stripe sends web customers to the restaurant's
  fixed success/cancel URL (a WhatsApp link for elas and sfcs). Deferred;
  options are in the plan, §13.1.
- **No session expiry.** Checkout stays payable for Stripe's default 24 hours;
  Ordelo needs a late-payment guard for web orders (plan Q17).
- **No idempotent session creation.** A retried create can leave an orphan
  Checkout Session; only the newest URL is shown.
- **Unknown restaurant falls back to Elai** inside the payment service, so
  Ordelo must reject a `rest_ref` the payment service doesn't know before
  calling it.
- **Never the automatic-capture call for web.** In the payment service,
  automatic-capture sessions print a kitchen ticket at authorisation.
- **Forged payment-complete events are an accepted risk.** One for an unpaid
  order would start fulfilment; capture then fails at the capture point and
  alerts.
