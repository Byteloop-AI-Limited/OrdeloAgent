# R3 live web ordering — local build and regression handover

## Status

Implemented locally on 2 October 2026 in OrdeloAgent and restaurant-frontend.
ELAS is the only enabled web restaurant, in Salisbury. This is a local regression
window through the existing Cloudflare tunnel, not a production deployment or
completed R3 acceptance. The owner requested that business identity, support
email, and approved Terms/Privacy links remain pending.

## Scope and WhatsApp implications

This release changes the backend as well as the storefront UI: guest checkout,
availability, immutable order/address snapshots, idempotent creation, secret
order links, order status, and late-payment cancellation. New web endpoints use
a server secret; browser order access requires a cookie or secret link. Web
orders have W customer IDs and WEB threads with no customer phone number.

The existing WhatsApp menu, basket, cart and checkout screens retain their flow.
Payment ingress, customer notification hooks, thread cleanup, and the rider
contact tool are shared backend code and therefore need regression testing.
Contract tests preserve WhatsApp URLs and payloads; these are not evidence of
new end-to-end WhatsApp delivery or collection tests.

The change has high release criticality because it creates real orders and
payment sessions. Test mode must be explicitly requested with
`?isTest3100=true`; being an enabled web restaurant does not itself force test
payments. The backend checks `TEST_PAYMENT_REST_REFS` and refuses an unauthorised
test-mode request rather than falling back to live payment.

## Implemented behavior

- `/web/*` live backend and frontend proxies, signed checkout cookies, same-origin
  mutations, bounded basket/address input, 20-line limit and server availability.
- Per-request and per-checkout locks, persistent idempotency records and recovery
  of a payment URL failure without creating a second order. Address snapshots
  are cloned to a new W customer for each order.
- Order-scoped random access grants stored as hashes, 30-day expiry, private
  status/receipt views, ETags, and saved-link exchange to a clean order URL.
- Manual payment capture through the existing payment-service contract. Late
  web authorisation after 35 minutes or restaurant closure queues cancellation
  durably and does not initialise fulfilment. Failed no-rider/collection-decline
  cancellations also queue recovery. Financial retries are separate from the
  unchanged zero-retry policy for attempted restaurant-app HTTP notifications.
- Web threads expire after two hours and are excluded from WhatsApp cleanup.
- A gated price-floor audit exists; it is not enabled in this test window.

## Bugs found and fixed

- Seven notification paths could send a W customer ID to a restaurant app when
  the notifier flag was off. Web events now remain in the web channel.
- The rider contact tool could try to send a synthetic ID as a contact number;
  web orders now give the rider the no-number instruction and ops fallback.
- Collection decline could send WhatsApp to a W ID and report cancellation as
  successful despite a failed payment-service call. It now records the actual
  result and queues recovery where needed.
- Payment status could infer capture/release from stale order fields. Views use
  verified events and completed cancellation records instead; polling continues
  while release/refund is pending.
- Checkout reuse could retain a removed/expired backend session. The frontend
  verifies it before reuse. Idempotency scope is shared across browser tabs.
- Saved-link and short restaurant redirects used the internal localhost origin
  behind Cloudflare. They now return relative Location headers.
- Invalid pricing responses could resemble out-of-range results; those errors
  are distinguished. Restaurant address display omits placeholder data.

During a disposable concurrency test, my initial harness left a session-level
database search path on the transaction pooler. An initial unpaid attempt
`ELAS-XBJN-1` landed in the scratch schema and could not be resumed. No payment
URL, payment or fulfilment resulted. The scratch schema was removed and public
foreign-key targets verified. The web transactions and migration now explicitly
select the public schema transaction-locally. The corrected harness uses only
transaction-local scratch settings and removes its schema. A fresh database
inspection confirmed no remaining `r3_check_%` schemas.

## Evidence

| Check | Result and limit |
|---|---|
| Backend suite | 533 passed, 1 deselected; 3 existing pywa deprecation warnings. The deselected `test_restaurant_master_get_admins_fetches_live_column` was reproduced and predates R3: the test expects a new fetch while current `get_admins()` returns its cached field. |
| Frontend | Production build passed; TypeScript and lint passed, with existing image/Edge dependency warnings. |
| SQL | R3 additive migration validated in a rollback transaction, then applied on the authorised shared Supabase project. RLS/revocations, RPC defaults and admin origin column retained. Original function definitions saved privately. |
| Disposable concurrency | Eight simultaneous same-key requests created one order and one payment URL. Replay reused it, changed body returned 409, and an interrupted payment URL call recovered without a duplicate order. External pricing/payment were mocked; this was not a Stripe connectivity test. |
| Real storefront | Chrome used the town/storefront, basket and collection checkout. Created `ELAS-GZBU-24`, two Vegetable Biryani, £27.90, `origin_channel=web`, `storefront=ordelo`, `payment_mode=test`, one item line and one access grant. |
| Payment | Quote and test label rendered. Database still reports `requires_payment`. No Pay action or fulfilment has occurred for this order. |
| Access | Backend rejects missing server secret and missing order access. Fresh Chrome incognito session showed only access help for the order number; a separate clean session exchanged the saved link, stayed on the public test host and displayed the correct £27.90 receipt. |

The order was placed at approximately 14:06 Europe/London (13:06 UTC) and the
Ordelo acceptance deadline is 14:41 local. Its note says this is a local
regression and not to prepare food. Stripe can keep the session payable longer
than the Ordelo deadline; the local late-payment guard must remain available.

## Owner WhatsApp delivery regression — ELAS-LXGM-26

The owner identified this as a WhatsApp delivery order from an **overwatch
number**. At 14:37 Europe/London (13:37 UTC), read-only database and Stripe
inspection confirmed:

- `origin_channel=whatsapp`, `storefront=direct`, an ELAS thread and an ordinary
  phone recipient (masked in the private inspection snapshots).
- Stored `payment_mode` is null. Existing `FoodOrder.uses_test_payment` chooses
  the test payment service for overwatch delivery when no explicit mode is set.
  Stripe independently confirms `livemode=false`; this is not a live-payment or
  non-overwatch customer regression.
- One authorised event, `evt_1UM6cP9Ci6shntN1NtOdKDS8`, and one delivery summary.
  PaymentIntent `pi_3UM6cO9Ci6shntN10N17Y14O` is persisted under short reference
  `LXGM-26`, unlike the failed manual-collection case below.
- Restaurant accepted. Rider dispatch **1216** was assigned at approximately
  14:36:47 local; delivery summary is `assigned`.
- Stripe reports **succeeded**, £28.37 received, zero capturable, manual capture:
  the normal rider-acceptance capture succeeded.
- `payment_authorised` and `rider_assigned:1216` each have one
  `whatsapp_restaurant` outbox row, status `sent`, attempts 1, no error. This
  proves successful restaurant-app adapter delivery, not independently observed
  receipt/rendering in the customer's WhatsApp app.

The owner subsequently confirmed pickup and entry of the customer confirmation
code, closing the order. A fresh inspection at **14:39 local (13:39 UTC)**
confirmed delivery summary, car delivery detail and dispatch **1216** all
`completed`. `food_collected` and `delivered` were recorded and each has one
`whatsapp_restaurant` outbox row, `sent`, attempts 1, no error. All four observed
customer events therefore have one successful adapter attempt. Stripe remains
`succeeded`, £28.37 received, zero capturable. The unchanged food_order value
`requires_capture` is stale and is not the financial outcome.

**The normal overwatch WhatsApp delivery lifecycle passed**: authorisation,
restaurant acceptance, rider assignment/capture, pickup and customer-confirmed
completion. This does not cover non-overwatch live payment, takeaway,
pay-at-restaurant or other failure paths. The owner's pickup/completion report
is human evidence; exact visual parity of every WhatsApp message was not
independently inspected by the agent. No test statuses were forced or
payment/provider state modified by the agent.

Private snapshots are `/private/tmp/ordelo-r3-wa-lxgm-26.json`,
`/private/tmp/ordelo-r3-wa-lxgm-26-after-accept.json` and
`/private/tmp/ordelo-r3-wa-lxgm-26-completed.json`.

## Regression steps still required

### Owner payment follow-up at 14:32 Europe/London

The owner paid a fresh collection order, **ELAS-RNRX-25**, rather than the
earlier unpaid GZBU quote. Stripe test authorisation and Ordelo ingress succeeded:
event `evt_1UM6ZI9Ci6shntN1Lwuye2Ar`, PaymentIntent
`pi_3UM6ZH9Ci6shntN10glZ8rYB`, £27.90, `livemode=false`, manual capture.
The order has one authorised payment event, a web-page subscription and no
restaurant-app customer notification. Normal collection timeout auto-accept set
the pickup time to 15:02 local and the summary is `pickup_confirmed`.

**Capture regression failed.** All three capture attempts received the explicit
payment-service lookup error: no payment details for `RNRX-25`. Fresh reads found
no payment_details under either short or full order reference. Stripe still
reports `requires_capture`, 2,790 pence capturable and zero received. No manual
capture, provider cancellation or database repair was performed by the agent.

The actual Checkout Session has `action=collection` but no `captureMode` or
`restRef` metadata. Event pending_webhooks is zero; both configured test
destinations remain enabled. This indicates a deployed payment-service version
or configuration mismatch: local payment-service commit `58158ca` writes
`captureMode=manual` and persists manual-collection intents before deferring the
receipt. The deployed Lambda version/logs have not been inspected, so this is a
supported diagnosis, not a verified deployment conclusion. A deployment of the
existing fix would be a separate authorised action. Existing sessions would
still need explicit reconciliation; deploying alone does not repair them.

This payment-service issue can also affect WhatsApp manual-capture collection.
Do not mark collection acceptance passed or imply a longer capture retry fixes
missing persistence. Keep the local test window open for the owner's WhatsApp
regression and record each order's independent result.

Open `https://restaurant-test.ordelo.app/town/salisbury?isTest3100=true` and confirm
the review page says **test mode** before proceeding to Stripe. Keep the saved
order link. Use Stripe test details only; the owner performs the payment step.

1. Web collection: authorise, accept/set and adjust pickup time, ready, collected;
   verify the live page and Stripe capture outcome. Repeat with natural decline.
2. Web delivery: address/changed fee, minimum spend, authorise, rider acceptance,
   capture, pickup and completion; check no customer number is offered to rider.
   On a separate order allow natural no-rider timeout and verify release.
3. Pay an older web test quote after the 35-minute deadline; verify no fulfilment
   init, eventual cancellation, and released wording. Keep this window open
   through cancellation/reconciliation.
4. Existing WhatsApp: delivery, takeaway and pay-at-restaurant through the real
   customer/admin/rider flows; compare customer messages and capture timing.
5. Browser behavior: two tabs/same basket, distinct baskets, refreshed checkout,
   changed address, saved-link return after closing browser, closing/paused
   restaurant and kill switch while an order remains in flight.

Provider-funded payment, actual restaurant/admin/rider transitions and the
complete R3 matrix remain unverified in this build run. The earlier R2 report
contains separate payment-service evidence and must not be presented as R3
storefront acceptance.

## Temporary configuration and restoration

Servers started by this session: Ordelo 3100 and frontend 3000. The existing
Cloudflare tunnel was preserved. Private logs are
`/private/tmp/ordelo-r3-backend-20261002.log` and
`/private/tmp/ordelo-r3-frontend-20261002.log`.

| Setting | Before | Current local regression window |
|---|---|---|
| `WEB_ORDERING_ENABLED_REST_REFS` | absent | `ELAS` |
| `WEB_LATE_PAYMENT_GUARD_ENABLED` | absent | `true` |
| Frontend web mode | exact original in private snapshot | `live` |
| Frontend backend URL | exact original in private snapshot | `http://127.0.0.1:3100` |
| ELAS Stripe TEST Ordelo webhook `we_1SIzY19Ci6shntN1CMsGX6xn` | `https://rider-agent.ordelo.app/payment-hooks/payment-complete` | `https://rider-agent-test.ordelo.app/payment-hooks/payment-complete` |

The Stripe endpoint remains test-only, enabled and subscribed to
`checkout.session.completed`; its other fields and the separate payment-service
endpoint were preserved. No live Stripe webhook or Meta configuration was
changed. Meta's business-account override was already the local test URL.

Existing shared `ORDELO_APP_URL` and `RESTAURANT_MENU_APP_URL` were already the test
URLs and remain unchanged. Payment inbox/order RPC/notifier remain enabled;
current notifier pilot is ELAS,BNAT and test-payment allowlist is BNAT,ELAS.
These shared routes also affect production consumers during this maintenance
window. Do not replace them with a presumed production profile.

Exact snapshots (private, mode 600) are:

- `/private/tmp/ordelo-r3-config-before.json`
- `/private/tmp/ordelo-r3-frontend-env-before`
- `/private/tmp/ordelo-r3-stripe-test-before.json`
- `/private/tmp/ordelo-r3-function-before.json`

Restoration is **pending intentionally while the owner runs regressions**.
Close the window by first pausing new web checkouts, resolving pending financial
jobs and expiring remaining unpaid Stripe TEST sessions through the authorised
test provider. Then restore the recorded test webhook URL and frontend env,
remove the two originally absent R3 config rows, remove the ignored backend
`.env.r3-local` secret file and restart/stop only session-owned processes after
checking current listeners. Verify all restored values/destinations and allow
for the config cache. Do not disable the late-payment guard or restore the old
callback while a test quote remains payable. Keep the additive migration and
order records; dropping them is not a feature-flag rollback.

## Public launch gates

Pending: the paid web and WhatsApp regressions above, Lighthouse mobile
accessibility ≥90, business/support/legal details, operational monitoring M1–M9
and enabled price-floor audit, and production access-log/token redaction checks.
Application query logging is redacted; Next development access logs can still
contain `/o/{token}` paths, so infrastructure privacy acceptance is not claimed.
Client-supplied pricing remains the explicitly accepted D8 risk; legacy endpoint
authentication and webhook-signature limitations are not resolved by the new
authenticated web router. Do not enable public live payments on this evidence.
