# Fixture storefront browser check — 2026-10-02

Tested in the user's existing Chrome session against
`https://restaurant-test.ordelo.app`, with `NEXT_PUBLIC_WEB_ORDERING_MODE=fixtures`.
This is frontend fixture evidence, not R2 payment-path acceptance.

## Observed results

- `/town/salisbury` loads with the explicit prototype/test-data banner.
- Postcode `SP1 2AB` returns three restaurants and delivery fee/minimum estimates.
- BNAT reports closed before its 11:00 opening, and Add buttons are disabled.
- ELAS menu permits adding Vegetable Biryani at £13.95.
- Basket and checkout retain the item. Public fixture address used:
  `10 Fixture Street, Salisbury, SP1 2AB`.
- Review shows £13.95 items + £0.99 service + £2.49 delivery = £17.43.
- Pay opens `/checkout/fixture-pay`, explicitly saying no card is charged.
- Simulated success opens the payment return page and then tracking for
  `ELAS-XDKM-54` on the correct test hostname.
- Tracking survives reload; payment authorised and restaurant accepted are visible.
- Automatic fixture progression reaches rider assigned/payment charged, on its
  way, rider nearby and delivered. The customer code disappears at delivery,
  the progress list completes and the full update timeline remains visible.
- Database reads for this fixture reference return zero rows in `food_order`,
  `delivery_summary`, `order_customer_event`, `order_notification_subscription`,
  and `payment_event` (short ID `XDKM-54`).

## Tracking-link issue

The canned delivered scenario's Full link (`/o/fx.delivered`) redirects to
`https://localhost:3000/town/salisbury/orders/SFCS-DLVD-27` and Chrome shows
`ERR_SSL_PROTOCOL_ERROR`. Navigating to the same clean page path on
`https://restaurant-test.ordelo.app` succeeds, with the full delivered timeline
and receipt visible.

Source: sibling frontend `app/(web)/o/[token]/route.ts` builds the absolute
redirect from `request.url`. The observed tunnel origin is wrong for this
redirect. No fix or configuration change was made during this check.

## Scope

No Stripe checkout, capture, cancellation, payment replay, real rider/admin
notification, or live notifier suppression was exercised. The frontend live
proxy remains R3 work; R2 needs a real web-origin API order.
