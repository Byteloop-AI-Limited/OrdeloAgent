# Collection capture investigation — 9 October 2026

## Finding

The observed collection capture failure is caused by the **payment-service test deployment and webhook wiring**, rather than OrdeloAgent failing to request manual capture or failing to trigger capture.

The test checkout/capture API runs `wrenPayment`. Stripe's test checkout webhook runs the separate `payment` Lambda. These deployments implement different versions of the payment contract. `wrenPayment` creates manual authorisations without `captureMode` or `restRef` metadata. The newer `payment` webhook consequently routes collection through its automatic-payment receipt branch and never writes the mapping required by capture.

This conclusion combines direct Stripe reads, database reads, API Gateway routing, deployed binary inspection, CloudWatch logs, the user's pasted wrenPayment logs, source history, and isolated tests. No payment, webhook, deployment, or database configuration was changed during this investigation.

## Verified payment state

Both affected orders are test-mode payments for £16.95. Direct Stripe reads confirmed:

| Order | PaymentIntent | Stripe status | Capture method | Received | Capturable | Charge captured |
|---|---|---|---|---|---|---|
| ELAS-YPYH-27 | `pi_3UOajK9Ci6shntN104kjaXAX` | `requires_capture` | `manual` | £0.00 | £16.95 | false |
| ELAS-UGMK-29 | `pi_3UOasP9Ci6shntN11qxlkaSW` | `requires_capture` | `manual` | £0.00 | £16.95 | false |

Neither had been captured at the time of the investigation. The latest charge's `status=succeeded` describes the successful authorisation; `captured=false` and `amount_captured=0` establish the capture outcome.

Ordelo's `food_order.payment_status` is `requires_capture` for both. Its `payment_event` table has an `authorised` event with the correct PaymentIntent ID for each. The payment service's separate `payment_details` table has no rows for either short or full order reference. This rules out merely storing the same mapping under `ELAS-UGMK-29` instead of `UGMK-29`.

The initial Stripe MCP connection exposed live mode only. This investigation subsequently read the test payments directly using the existing configured test credentials, without exposing those credentials.

## Intended contract and the August change

OrdeloAgent commit `9aeb97d`, dated 25 August 2026, changed online collection from immediate automatic payment to manual authorisation followed by capture when pickup time is established. Pay-at-restaurant retains its separate print-only path.

The collection checkout helper sends `action=collection`, `manual_mode_capture=true`, `printonlyjob=false`, and `restRef`. The web checkout selects that helper for collection. The pickup-time webhook schedules `capture_takeaway_payment`, which sends `payment_mode=capture` and the short `order_id` to the order's configured payment endpoint.

Payment-service commit `58158ca`, also dated 25 August, addressed the matching contract:

1. Record `captureMode=manual` on both the Checkout Session and PaymentIntent.
2. Store the PaymentIntent at checkout completion for any manual payment, including collection.
3. Defer receipt printing until capture.
4. Propagate capture failures and avoid a receipt on a failed capture.

Before that fix, the webhook saved the PaymentIntent only when `action=delivery`. Collection could be manually authorised while still taking the automatic receipt branch. The current webhook preserves delivery compatibility without captureMode, but does not classify a legacy collection session without that metadata as manual.

Collection and delivery now share the authorisation/capture mechanism, but the business triggers differ: collection captures at pickup-time establishment; delivery captures at its delivery assignment flow.

## Actual deployed topology

| Responsibility | Configured endpoint | Lambda |
|---|---|---|
| Test Checkout Session creation and capture | `0af50z1k40.execute-api.eu-west-2.amazonaws.com/prod/threads/{threadID}/orders/{orderID}/payment-url` | `wrenPayment` |
| Stripe test checkout webhook | `hjgttc1wpj.execute-api.eu-west-2.amazonaws.com/prod/webhook/elai` | `payment` |
| Ordelo authorisation callback | `rider-agent-test.ordelo.app/payment-hooks/payment-complete` | OrdeloAgent |

API Gateway integrations were read directly, rather than inferred from endpoint names. Both Stripe test webhook destinations are enabled for `checkout.session.completed`.

Lambda deployment metadata:

- `wrenPayment`: last modified 8 October 2026 at 16:29:34 UTC; runtime `provided.al2023`.
- `payment`: last modified 28 August 2026 at 13:53:51 UTC; runtime `provided.al2`.

The later date on wrenPayment does not establish that it contains the August fix. Read-only inspection of its deployed bootstrap found the legacy capture error wording and **no** `captureMode`, manual-authorisation deferral message, or `HandleCapture:` marker. The deployed `payment` bootstrap contains all three newer markers and lacks the legacy error wording. Git revision information was unavailable in these binaries; no exact source commit is claimed for wrenPayment.

The repository's `buildspec.yml` deploys only `--function-name payment`. It does not update wrenPayment. This is a concrete explanation for how a corrected repository and webhook can coexist with an incompatible test producer/capture service; the exact historical process that built wrenPayment was not established.

## UGMK-29 timeline and failure chain

Times below are Europe/London (BST). AWS's pasted timestamps are UTC and therefore one hour earlier.

| Time | Evidence |
|---|---|
| 11:16:48 | wrenPayment receives collection checkout with `ManualModeCapture:true`; Stripe creates a test manual payment. |
| 11:18:11 | Ordelo applies the Stripe authorisation event and records the PaymentIntent in `payment_event`. |
| 11:18:12 | The separate `payment` webhook logs `action=collection`, `restRef=""`, then `Action: collection`; it does not enter the manual-authorisation storage branch. |
| 11:18:12 | That webhook attempts to read the test Checkout Session through the live Stripe account and receives `404 No such checkout session`. It then reports a successful printer HTTP request. Physical printing was not verified. |
| 11:18:52 | Ordelo's pickup-time webhook triggers collection capture. wrenPayment cannot find UGMK-29 in `payment_details`. |
| 11:18:54 | Second attempt fails with the same lookup error. |
| 11:18:59 | Third attempt fails with the same lookup error; Ordelo reports capture failure and starts its reconciliation alert path. |

Direct retrieval of the completed Stripe Session confirmed that its metadata contains `action`, `orderID`, `threadID`, `recipient`, and `notes`, but lacks `captureMode` and `restRef`. The PaymentIntent has the same missing fields despite `capture_method=manual`.

The current webhook's decision is effectively:

```text
captureMode == manual -> save PaymentIntent, return before printing
otherwise action == delivery -> save PaymentIntent, return before printing
otherwise -> automatic receipt branch, no PaymentIntent mapping
```

UGMK-29 satisfies neither storage condition. This directly explains the absent mapping. The webhook was delivered and executed; it was not simply missing or delayed. The first capture was about 40 seconds after authorisation. The 2-second and 5-second retries cannot repair a deterministically skipped storage branch.

The Stripe account mismatch is a second confirmed payment-service configuration defect: the test webhook destination invokes the live-configured `payment` Lambda, and the source's empty-restRef fallback selects Elai. CloudWatch's failed line-item request identifies the live account `acct_1SHtos6e6G5Xg3P5`; the test Session belongs to the test account. Missing capture metadata causes the observed storage failure even before that wrong-account API call.

## Interpreting the pasted wrenPayment logs

The pasted logs show, within each capture invocation:

```text
Failed to capture payment: ... no payment details found for order number: UGMK-29
Captured successfully for order number UGMK-29
```

The second message is false as a payment outcome. All three requests returned HTTP 500 to Ordelo, and Stripe still reports £0 received and `captured=false`. This is consistent with the old handler's use of a nil Go error alongside an HTTP 500 response; downstream code can incorrectly treat the nil error as success. The deployed fork's exact source is unavailable, so its precise logging implementation is not asserted.

Capture request logs show `ManualModeCapture:false`. This is not the problem: capture uses `payment_mode=capture`, while the manual flag is relevant when creating a Session. The original creation requests correctly show `ManualModeCapture:true`.

## Service attribution

**Confirmed primary fault: payment-service's deployed test flow.** Its producer, webhook, account selection, and capture lookup disagree.

For this order, OrdeloAgent performed the required actions: requested manual capture, received and persisted authorisation evidence, triggered capture at pickup-time establishment, used the correct order ID, retried the explicit pre-capture lookup failure, and reported the final HTTP failure. Increasing its retries or reverting collection to automatic payment would not repair the underlying mismatch.

The fact that Ordelo stores the PaymentIntent in `payment_event` does not satisfy payment-service's contract: capture reads `payment_details`. Sharing a fallback lookup could reduce fragility, but it would be a deliberate cross-service contract change, not evidence that Ordelo failed its current responsibility.

## Recommended repair order

1. Align the test checkout/capture deployment with the manual-collection contract: Session and PaymentIntent must contain `captureMode=manual`, `restRef`, and matching order identifiers. Remove false capture-success reporting.
2. Route the Stripe test webhook to a compatible handler using the same test account and database as the producer/capture service. Do not blindly deploy the repository's live-configured entrypoint to wrenPayment: its configuration must preserve test credentials and valid test payout destinations.
3. For existing sessions created without captureMode, define explicit reconciliation/compatibility handling. Replaying the current webhook with unchanged metadata would still take the wrong branch. A newly deployed producer also does not retrofit old sessions.
4. Validate with a fresh test collection: manual authorisation, mapping persisted, no receipt at authorisation, pickup-time capture, Stripe `captured=true`, correct payout destination, and one capture-time receipt. Then exercise delivery and automatic collection compatibility.

For legacy compatibility, do not simply treat every `action=collection` as manual: historical automatic collections exist. Use verified Stripe capture state and the correct account when resolving ambiguous legacy metadata. Historical reconciliation must check current Stripe state before attempting any capture or refund.

## Validation and limits

- Existing manual-capture webhook tests pass for delivery, takeaway, and collection in an isolated copy of the repository.
- An additional isolated incident test reproduces the exact compatibility boundary: collection without captureMode skips storage; collection with `captureMode=manual` enters storage; legacy delivery without captureMode still enters storage.
- `go test ./...` encountered a pre-existing vet error in `storage/repo.go:63`: `%s` formats an integer HTTP status. With vet disabled, all package tests pass. Dependencies and test additions were confined to a temporary copy; the payment-service checkout was not modified.
- Tests establish current source behavior, not successful deployment of a repaired test stack. No repair or end-to-end retest has been performed.
- Related robustness gaps in current source include no failure when a manual Session lacks a PaymentIntent, no checked line-item iterator error before printing, and no idempotent payment-details insert. These were observed in code but did not cause the specific skipped-branch failure established above.

## Source pointers

- `payment-service/internal/stripe/payment.go:126`: capture metadata creation.
- `payment-service/internal/stripe/webhook.go:58`: manual/delivery branch decision.
- `payment-service/internal/stripe/webhook.go:97`: PaymentIntent mapping persistence.
- `payment-service/internal/stripe/webhook.go:107`: automatic receipt branch and Stripe account selection.
- `payment-service/internal/stripe/payment.go:178`: mapping lookup before capture.
- `payment-service/internal/config/config.go`: restaurant fallback and live Secrets Manager configuration.
- `payment-service/buildspec.yml:18`: deployment targets only payment.
- `OrdeloAgent/utils_common/payment_ms/payment.py:78`: manual collection checkout.
- `OrdeloAgent/utils_common/web_ordering/web_checkout.py:439`: web collection helper selection.
- `OrdeloAgent/watomation/routers/takeaway_hooks.py:580`: pickup-time capture scheduling.
- `OrdeloAgent/utils_common/payment_ms/payment_events.py:72`: Ordelo authorisation PaymentIntent parsing.
