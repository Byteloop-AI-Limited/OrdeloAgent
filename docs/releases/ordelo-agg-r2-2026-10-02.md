# R2 payment-path verification — 2026-10-02

User authorized an ELAS test using the basket/address from `ELAS-LXGM-21`.
The planned orders use fresh W-ids and WEB threads, `origin_channel=web`,
`storefront=ordelo`, and `test_payment=true`. This is separate from the fixture
browser order `ELAS-XDKM-54`, which created no real database order.

## Preflight

Configuration read confirms payment inbox, atomic order creation and customer
notifier enabled. Notifier/test-payment scopes both include ELAS and BNAT.
`ORDELO_APP_URL` points to `https://rider-agent-test.ordelo.app`.

Read-only Stripe API inspection of the configured ELAS test account found:

| Endpoint ID | URL | Event | State |
| --- | --- | --- | --- |
| `we_1SIzY19Ci6shntN1CMsGX6xn` | `https://rider-agent.ordelo.app/payment-hooks/payment-complete` | `checkout.session.completed` | enabled, test mode |
| `we_1SItMu9Ci6shntN1jw81tGYb` | `https://hjgttc1wpj.execute-api.eu-west-2.amazonaws.com/prod/webhook/elai` | `checkout.session.completed` | enabled, test mode |

The Ordelo test event destination points to production, explaining why local
Meta routing alone is insufficient to test payment notifications. This is the
likely cause of the earlier missing `payment_authorised` notifier event; the
historic production request logs have not been inspected.

The user approved temporarily changing the first endpoint to
`https://rider-agent-test.ordelo.app/payment-hooks/payment-complete`.
That change was applied and verified in Stripe test mode. The payment-service
endpoint and live-mode endpoints were not changed. After both checks completed,
the Ordelo test endpoint was restored to its exact original URL above, and
verified with a fresh Stripe GET. It remains enabled, `livemode=false`, subscribed
to `checkout.session.completed`; the payment-service destination remains unchanged.

## Prior payment_details correction

The payment service stores short `order_id` values in its `order_number` column.
For example, the PaymentIntent for the approved baseline is present under
`LXGM-21`, not `ELAS-LXGM-21`. The manual verification guide is corrected.

Read-only Stripe inspection also confirms that baseline PaymentIntent
`pi_3UM2de9Ci6shntN11JlbvUuw` is `succeeded`, `livemode=false`, amount 2,837
pence, amount received 2,837 pence, amount capturable zero. Test capture did
occur; the missing customer event is separate from capture.

## Execution and evidence

This run uses ELAS by explicit user approval, rather than the plan's BNAT default.
Both orders use the approved basket: two Vegetable Biryani at £12.56 each,
£1.76 service charge and £1.49 delivery, total £28.37. The existing local
storefront remains in fixture mode; real R2 orders were created through the
existing Swagger UI endpoints and paid through Chrome's Stripe sandbox. This
does not establish that the town storefront creates live orders (R3).

### Order A: ELAS-DQFH-22

Created with W-id `W23LA6EL2MDC`, fresh WEB thread, `origin_channel=web`,
`storefront=ordelo`, and `payment_mode=test`.

| Check | Observed result |
| --- | --- |
| Authorization | Stripe PI `pi_3UM3WN9Ci6shntN11SvGg32H` initially `requires_capture`, 2,837 pence capturable, `livemode=false`; `payment_details` stores it under `DQFH-22`. |
| Ordelo initialization | One authorized payment event (`evt_1UM3WO9Ci6shntN1PXsd8hMh`) and one delivery summary. |
| Customer routing | Subscription 3 is `web_page`, destination null; `payment_authorised` event 5 and `rider_assigned:1215` event 6 each have one outbox row, `skipped`, attempts 1, no error. |
| Replay | Three POSTs of the original Stripe event returned HTTP 200 and `outcome=duplicate`; one summary and one authorization/customer event remained. Three diagnostic `authorised_duplicate` records were added intentionally. |
| Capture | User accepted dispatch 1215. Stripe subsequently reported `succeeded`, 2,837 pence received, zero capturable; delivery summary and dispatch were assigned. |
| Redirect | Chrome reached `https://api.whatsapp.com/message/AIDICBLAE4KZH1?autoload=1&app_absent=0`, via the configured `https://wa.me/message/AIDICBLAE4KZH1`. No customer WhatsApp message was sent by the tester. |

The skipped outbox rows and the web adapter's implementation establish notifier
suppression for these observed events. Restaurant-app access logs were not
audited. Skipped web delivery is intentional in R1b and does not mean the current
fixture order page consumed the events; live order-page polling belongs to R3.

### Order B: ELAS-SSPB-23

Created with W-id `WMHKYIRLCVCL`, a separate WEB thread and the same web/test
settings. Chrome displays the £28.37 Stripe sandbox checkout with generic test
card 4242. Automatic approval review rejected the agent's final Pay click and
required user hand-off; the user submitted the test payment.

At 10:27:24 UTC, Ordelo recorded authorized payment event 18
(`evt_1UM3gV9Ci6shntN1r1vhZZlb`) and initialized one delivery summary. Stripe
PI `pi_3UM3gU9Ci6shntN102kKFudl` is `requires_capture`, with 2,837 pence
capturable and zero received, `livemode=false`. The payment service stored the
PI under `SSPB-23`. Customer event 7 is `payment_authorised`; subscription 4
is `web_page` with no destination, and outbox 7 is skipped, attempts 1, no error.
Chrome again reached Elai's configured WhatsApp redirect.

The normal scheduler exhausted all four vehicle types without creating a rider
dispatch, then changed the summary to `timedout`. At 10:32:30 UTC (11:32:30 BST),
customer event 8 recorded `no_rider_found` with `data.payload.payment_cancelled=true`.
Its outbox row 8 is skipped, attempts 1, no error. A fresh Stripe read at 10:32:55
UTC confirmed PI `canceled`, zero received and zero capturable, `livemode=false`.
This was the configured five-minute timeout, without forcing cancellation,
delivery status, timeout or rider availability.

`food_order.payment_status` remains `requires_capture` after this cancellation
(also after A's successful capture). Stripe is the verified source for the actual
financial result in this run; these existing order-table values should not be
presented as evidence that a capture or release failed.

## Acceptance status

The five R2 payment-path checks pass for the approved ELAS test scope:
authorization/payment persistence, web notifier suppression, duplicate-event
handling, capture on acceptance plus natural no-rider cancellation, and observed
browser redirect. No BNAT or other Stripe account was retested during this run.
The temporary ELAS test webhook has been restored. No code deployment, new SQL,
payment-service change or ordelo_config mutation was made by this R2 run.

The accepted test job for A was still assigned at the last inspection; the user
must complete or resolve it through the normal rider flow. Neither test proves
R3's live storefront, polling, or post-payment return page.

## Logs and evidence limits

The user's Ordelo processes (19164/19166, port 3100) write stdout/stderr to
`/dev/ttys007`. Computer use denied access to Ghostty, so the current console
logs and restaurant-app access logs were not inspected. No older stopped-server
log was used as evidence. Runtime conclusions above rely on the endpoint
responses, current database records and read-only Stripe API observations.

Evidence snapshots are in `/private/tmp/ordelo-r2-a-authorised-evidence.json`,
`/private/tmp/ordelo-r2-a-replay-evidence.json`,
`/private/tmp/ordelo-r2-a-capture-evidence.json`,
`/private/tmp/ordelo-r2-b-current-evidence.json` and
`/private/tmp/ordelo-r2-webhook-restoration.json` (temporary local files).
