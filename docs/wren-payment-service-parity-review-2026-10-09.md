# Wren/payment-service parity review — 9 October 2026

## Conclusion

`wren-payment-service` is not currently a test-configured copy of `payment-service`. Its checkout and capture mechanisms exist, but its request contract, collection authorisation storage, restaurant routing, receipts, return URLs, logging, tests, and deployment configuration have diverged.

The clone validates the earlier incident diagnosis directly. Wren can create a Stripe manual authorisation for a collection, but its webhook saves the PaymentIntent only for delivery. Capture subsequently reads a mapping that collection never stored. Its handler also logs capture success for an HTTP 500 failure.

The intended target is the same payment implementation behind both existing API endpoints, with explicit environment configuration selecting test or live Stripe credentials, matching Connect destinations, webhook credentials, and operational destinations. A test URL should result from using the correct test credentials throughout the lifecycle; changing only the checkout URL would not make capture, cancellation, transfers, or webhook reads test-mode operations.

## Scope and evidence

- Wren clone: `/Users/basavaraj/bloop/wren-payment-service`, HEAD `2aa1ecb`; its two commits are dated 29 December 2025.
- Current production-service source: `/Users/basavaraj/bloop/payment-service`, HEAD `dcebbe0`.
- Ordelo routing: `utils_common/order_management/food_order_pymodel.py:196-223`.
- Read-only comparison of common source files, additional modules, tests, dependency declarations, and commit history.
- Existing Chrome AWS tab inspected through computer use, including Code, General configuration, and Triggers.
- Read-only AWS API Gateway and Lambda configuration checks.
- Previously retrieved deployed binaries examined for feature markers; previous Stripe, database, and CloudWatch incident evidence retained in `payment-service-investigation-2026-10-09.md`.
- Two isolated Wren regression checks reproduced collection storage and false capture-success logging without invoking Stripe or Supabase.

Neither service checkout was modified. No deployment, payment, webhook, credential, or AWS configuration changes were made.

## What is already equivalent

| Area | Finding |
|---|---|
| Order endpoint shape | Both use `POST /threads/{threadID}/orders/{orderID}/payment-url`. |
| Ordelo endpoint selection | An order marked `payment_mode=test` selects `stripe_url_test`; live selects `stripe_url`. The order/thread identifiers are constructed consistently. |
| Stripe manual authorisation primitive | Both can create a Checkout Session with `payment_intent_data.capture_method=manual`. |
| Capture primitive | Both look up the stored PaymentIntent, request the capture amount, and transfer the restaurant payout using `latest_charge` as the source transaction. |
| Cancellation primitive | Both look up the stored PaymentIntent and call Stripe cancellation. |
| Currency and amount conversion | Both use GBP and round pound amounts into integer pence. |
| Database repository | `storage/repo.go` is byte-for-byte identical. Both use the same Supabase project and `payment_details` table. |
| Declared dependencies | `go.mod` differs only in module name; Go and declared dependency versions match. |
| Gateway authentication shape | Both order routes use a custom authorizer and equivalent path-to-query parameter mappings. Authorizer internals were not compared. |

These similarities explain why Wren can provide a usable test checkout link without providing a faithful test of the complete production flow.

## Missing or divergent behavior

| Area | Current payment-service source | Wren clone | Consequence |
|---|---|---|---|
| Capture metadata | Stores `captureMode` on Session and PaymentIntent. | Does not store it. | The newer webhook cannot identify manual collections from metadata. |
| Restaurant metadata | Stores `restRef` and `riderCode`. | Neither is in the request model/Stripe metadata path. | Restaurant selection and receipt context are lost. |
| Collection authorisation storage | Manual payments are stored regardless of delivery/collection action. | Only `action=delivery` stores the PaymentIntent. | Collection capture fails with missing payment details. |
| Capture receipt action | Returns action from the captured PaymentIntent, with a legacy request fallback. | Capture returns only an error. | Does not preserve production receipt behavior. |
| Capture outcome logging | New capture handler handles the failed capture response before continuing. | Logs success when the wrapper returns nil Go error, even if HTTP status is 500. | False success messages conceal failed capture. |
| Restaurant routing | Configurations for Elai, SFC, and Burger Nation with their keys, account IDs, URLs, printer destinations, and alerts. | One Stripe test key and one Wren Connect destination for every request. | Tests do not exercise production restaurant selection. |
| Item modifications | Accepts modifications and carries them through product metadata/receipts. | Only product name, quantity, and price are modeled. | Customisations are dropped. |
| Print-only orders | Handles `printonlyjob` before payment creation. | The field is absent; unknown JSON fields are ignored. | A print-only request can instead create a checkout, or fail ordinary payment validation. |
| Receipt/print integration | Includes `internal/client` for capture receipts, automatic-payment receipts, print-only receipts, and alert emails. | No client package or receipt path. | Testing omits all kitchen receipt behavior. |
| Per-order return URLs | Optional `success_url`/`cancel_url` with per-field defaults, host validation, and token masking. | Ignores both fields; hardcodes Elai WhatsApp URLs. | Web customers would not follow production's return flow when using this clone. |
| Restaurant-specific defaults | Restaurant-configured success/cancel URLs. | One hardcoded WhatsApp return destination. | Restaurant redirect differences cannot be tested. |
| Secret order-link logging | Current request logging masks `/o/<token>` credentials. | Full requests and parsed bodies are logged without that helper. | New caller fields may expose order-link tokens even when ignored. |
| Tests | Manual capture/webhook, restaurant configuration, return-URL, and local runner tests. | No Go test files in the clone. | Contract drift has no regression coverage. |
| Local runner | `cmd/local` with embedded test configuration and a test-key guard. | No equivalent runner. | Local parity validation is missing. |
| Deployment target | Deploys to Lambda `payment`. | Also deploys to Lambda `payment`. | Wren's buildspec could overwrite the production Lambda with the test implementation. |

Both services still print complete secret maps from their Secrets Manager configuration loaders. That is a shared source issue, not an additional Wren-only difference. The same is true of the repository's integer HTTP-status formatting vet error and its non-idempotent mapping insert.

## Source-level validation of the incident

Wren `internal/stripe/payment.go:100-120` correctly applies manual Stripe capture but only records `action`, `orderID`, `threadID`, `recipient`, and `notes`. This matches the metadata retrieved from the affected real test Sessions and PaymentIntents.

Wren `internal/stripe/webhook.go:64-74` stores a PaymentIntent only inside:

```go
if strings.ToLower(action) == ActionDelivery {
    // SavePaymentDetails(...)
}
```

Manual collection bypasses this branch, even if a caller supplies `captureMode=manual` in the webhook payload. That is exactly what the isolated storage-contract test found: delivery saved one mapping; collection saved zero.

Wren `internal/transport/http/handler.go:139-147` returns an HTTP 500 response with a nil Go error on capture failure. Its caller at lines 93-95 checks only the Go error before logging `Captured successfully`. The isolated handler test reproduced that exact misleading log.

The August production fix, commit `58158ca`, introduces captureMode metadata and a webhook decision based on manual capture, with a legacy delivery fallback. This fix and its regression tests are absent from the Wren clone.

In the observed deployment, the Stripe test webhook does not call Wren's own webhook handler. It calls the newer production `payment` handler instead. Wren's missing metadata makes that handler choose its automatic collection/receipt branch, also skipping storage. Therefore **pointing the webhook at the unchanged Wren clone would not fix the incident**: its delivery-only rule has the same collection-storage defect.

## AWS deployment reality

| Property | Production | Wren/test |
|---|---|---|
| Order API base | `https://z0hydw9v90.execute-api.eu-west-2.amazonaws.com/prod` | `https://0af50z1k40.execute-api.eu-west-2.amazonaws.com/prod` |
| Integrated Lambda | `payment` | `wrenPayment` |
| Last code modification | 28 August 2026, 13:53:51 UTC | 8 October 2026, 16:29:34 UTC |
| Runtime | `provided.al2` | `provided.al2023` |
| Architecture | x86_64 | x86_64 |
| Memory | 128 MB | 128 MB |
| Lambda timeout | 300 seconds | 3 seconds |
| Gateway integration timeout | 30 seconds | 30 seconds |
| Deployed captureMode/new capture handler | Present | Absent |
| Deployed per-order return-URL handler | Absent | Present |

The Chrome Code tab confirmed Wren's deployed package hash is `58NfgPElIvId2Sagqd4b25VCZVA5FNXGH7AG/8GWHqY=` and contains a compiled `bootstrap`, rather than browsable Go source. It matches the package inspected earlier in the investigation.

There are three distinct states to keep separate:

1. **Wren clone:** December 2025 source; no newer collection handling or return-URL helper.
2. **Deployed wrenPayment:** has newer per-order return-URL handling, but lacks the manual-collection metadata/storage contract. The exact build source is not present in this clone.
3. **Deployed payment:** has the August manual-collection fix, but lacks the October return-URL handler found in current production-service source.

The browser Triggers panel also shows two obsolete references to APIs `ij2cwpemf0` and `raq3wjmk7c` that AWS reports as missing. The active Wren order API is `0af50z1k40`. These stale references did not cause the observed order capture failure.

The previously verified enabled Stripe test webhook points to `https://hjgttc1wpj.execute-api.eu-west-2.amazonaws.com/prod/webhook/elai`, whose Lambda integration is `payment`. Its test event entered the live-configured automatic receipt branch and attempted to retrieve a test Session through the live Stripe account. That account mismatch is an additional configuration defect to resolve alongside code parity.

## Target design

Use one canonical payment implementation and deploy it twice, retaining the two existing order endpoints. Differences should be configuration values rather than separately maintained checkout/capture/webhook logic.

| Setting | Production deployment | Test deployment |
|---|---|---|
| Payment implementation/version | Same release | Same release |
| Stripe credentials | Restaurant's live credentials | Corresponding configured test credentials |
| Connect payout destination | Restaurant's live destination | Valid test destination in the same test platform/account |
| Stripe webhook handler logic | Same implementation | Same implementation |
| Webhook account, mode, signing secret | Production-specific | Test-specific |
| Restaurant identity and metadata | Same supported restRefs | Same supported restRefs |
| Printer/alert behavior | Production destinations | Configured test destinations using the same contract |
| Return-URL behavior/validation | Same logic, production defaults | Same logic, test defaults |
| Deployment function name | `payment` | `wrenPayment` |

The test deployment must reject live Stripe credentials at startup, and the whole path must use the selected environment: creation, webhook Stripe reads, capture, cancellation, and Connect transfers. A valid test checkout URL alone is not sufficient proof.

Ordelo's existing `payment_uri` selection can remain the boundary. It already routes an order consistently by its saved payment mode; the downstream endpoint must provide the full equivalent contract.

The shared database repository can remain unchanged for parity work, since the services already share it. However, it keys mappings solely by order reference and contains no account/mode columns. Before changing the deployment topology, verify uniqueness of order references across environments; if collisions are possible, environment/account-aware storage should be a coordinated change in both deployments.

For long-term maintenance, a single repository or shared module plus a two-target deployment is preferable to copying production files into Wren repeatedly. If two repositories must remain, pin Wren to an explicit production version and automate parity checks; allow only documented configuration/deployment differences.

## Proposed implementation sequence

1. Recover or reconcile the actual deployed Wren return-URL changes before choosing the source baseline. The clone alone does not reproduce the existing web-return behavior.
2. Use current `payment-service` as the functional baseline and preserve one copy of the checkout, capture, cancellation, webhook, receipt, and request-schema logic.
3. Add explicit test configuration for every supported restaurant, plus test-only credential assertions. Preserve test payout accounts and test operational destinations rather than copying live configuration wholesale.
4. Fix Wren's deployment target to `wrenPayment`; record source revision/build identity in both artifacts and use the same release version.
5. Align test webhook routing/account settings and operational timeout settings. Matching Lambda timeouts alone does not bypass the shared 30-second API Gateway timeout; realistic network/print delays must be covered.
6. Bring over production contract tests and add cross-environment parity tests. Include the two incident regressions and the legacy/manual/automatic collection boundaries.
7. Validate a fresh test order through authorisation, persisted mapping, pickup-time capture, correct test transfer, and one capture-time receipt. Also validate delivery, print-only, cancellation, modifications, and web return URLs.
8. Handle existing authorised orders through explicit reconciliation. New checkout metadata does not repair already-created Sessions, and unchanged webhook replay still skips the storage branch.

This sequence is a proposed approach. The current request was fulfilled as comparison and validation; service implementation and deployment were not performed.

## Validation results

In a temporary copy of Wren:

- Manual delivery mapping test: **passes**.
- Manual collection mapping test: **fails**, with `saved 0 PaymentIntents, want 1`.
- Failed capture logging test: **fails**, with `HTTP 500 capture failure is incorrectly logged as Captured successfully`.
- These are diagnostic tests added outside the checkout. They do not invoke real Stripe, database, email, or printer services.

Earlier in this investigation, the production-source manual collection/storage tests passed, and all production-source package tests passed with vet disabled. Normal testing has a shared pre-existing vet error at `storage/repo.go:63` (`%s` used for an integer status). Neither source test result proves end-to-end deployment parity.

Stripe's documentation describes using test API keys and test payments to exercise the integration and testing webhook handling as part of that integration: https://docs.stripe.com/testing/overview. The recommended same-code/two-configurations design is an engineering conclusion from the observed drift, not a claim that Stripe requires this repository structure.
