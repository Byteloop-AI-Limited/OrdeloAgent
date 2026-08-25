# ADR 0002: Authorize takeaway payments at checkout and capture at pickup time

## Status

Accepted

## Decision

Online takeaway orders create a manual-capture Checkout Session. Ordelo keeps
`food_order.action='takeaway'`, while the payment-service request action is
`collection` for both authorization and capture.

The payment-service webhook records the PaymentIntent at authorization and
does not print. The first finalized takeaway `pickup_time` is the capture
boundary: the existing UPDATE trigger handles normal and timeout acceptance,
and the INSERT trigger handles configured auto-accept.

Capture receipt items contain product rows only for both delivery and
collection. `total_amount` remains the complete authorized amount, including
delivery fees where applicable. Takeaway capture supplies
`restaurant_confirmation_code='N/A'` without validation.

Ordelo retries capture only when the payment service explicitly reports that
the PaymentIntent is not yet stored. It makes three attempts in total, with
2-second and 5-second waits. Timeouts and all other capture, payout, or printer
failures require reconciliation and are not retried.

## Consequences

- A successful online takeaway produces one collection receipt at capture, not
  at authorization.
- Pay-at-restaurant retains its existing print-only path.
- The pickup-time endpoint still acknowledges the database trigger immediately;
  background operations remain ordered and continue after capture failure.
- No new `food_order.payment_status` is introduced.
- The payment-service and takeaway SQL contracts are unchanged.
