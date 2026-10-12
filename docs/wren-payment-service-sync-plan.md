# Wren payment-service synchronisation plan

Prepared 9 October 2026. This is an implementation plan, not a completed service migration.

## Objective

Bring `/Users/basavaraj/bloop/wren-payment-service` into functional parity with `/Users/basavaraj/bloop/payment-service`, while every Wren Stripe operation continues to use the existing test Stripe account. Retain the existing Ordelo test endpoint and Wren repository/module identity.

Baseline: production-service source `dcebbe0`; Wren source `2aa1ecb`. Recheck both working trees and revisions before implementation and preserve unrelated changes.

## Configuration contract

- Preserve Wren's existing Secrets Manager inputs: `stripetestkey` from `prod/elai/secrets`, and `wrenaccountid` plus the database key from `prod/ordelo/secrets`.
- Populate production-compatible restaurant configurations for all supported restRefs, using Wren's existing test Stripe key and Wren test Connect destination for every restaurant. Preserve restaurant names, metadata, return-URL rules, receipt behavior, and configured operational destinations from the functional baseline.
- Use the same selected test credentials for checkout creation, webhook Stripe reads, capture, cancellation, and transfers. Do not copy production's live-key overlays.
- Reject live or missing Stripe credentials at Wren startup. Validate the complete effective restaurant configuration, including embedded fallback configuration. Never print secret maps.
- Retain the same database repository and order-ID format. Verify that the configured Wren payout destination belongs to the selected test account before an eventual end-to-end test.

The test key and matching test payout account are the intended payment-environment differences. Separate module names and Lambda deployment targets are packaging differences, not changes to the order flow.

## Implementation steps

1. **Synchronise shared service behavior.** Bring over production's Stripe/payment logic, webhook, HTTP request handler, receipt/print/email client, common context, return-URL validation/redaction, and local runner. Rewrite imports for the Wren module. Keep the implementation equivalent to the pinned production baseline rather than making unrelated architectural or SDK upgrades.
2. **Adapt configuration to test-only operation.** Expose the configuration shape expected by the synchronised code while loading Wren's existing test credentials/destination. Initialise both payment and webhook paths through that configuration. Preserve restaurant routing semantics without selecting live credentials.
3. **Restore the full wire contract.** Support `restRef`, `rider_code`, item `modifications`, `printonlyjob`, and optional `success_url`/`cancel_url`, alongside existing fields. Write `captureMode`, restaurant identity, and other production metadata to both Checkout Sessions and manual PaymentIntents.
4. **Restore the manual collection lifecycle.** On authorisation, store PaymentIntents for all manual orders, including collection, and defer printing. At capture, use the same capture/transfer/receipt behavior as production. Remove the erroneous success log on an HTTP failure. Preserve automatic collection and pay-at-restaurant print-only behavior.
5. **Bring over production tests and add test-environment checks.** Adapt existing production tests only for Wren's configuration/module identity. Add the two incident regressions and verify that every restaurant's effective payment configuration is test-only. Establish a documented comparison of shared code, allowing only configuration, module imports, tests specific to the test account, and deployment packaging to differ.
6. **Validate and document.** Run meaningful tests, static checks, and a Linux/amd64 Lambda build. Record the production baseline revision, permitted differences, configuration contract, and deployment target in Wren documentation.

## Buildspec correction

The separately authorised one-line correction changes only the Lambda target:

```diff
- aws lambda update-function-code --function-name payment --zip-file fileb://payment.zip
+ aws lambda update-function-code --function-name wrenPayment --zip-file fileb://payment.zip
```

The build and ZIP artifact format remain unchanged. Editing this file does not deploy anything. Do not push or trigger its pipeline as part of planning.

## Acceptance criteria

- Every Wren checkout uses test Stripe credentials; live credentials are rejected before serving requests.
- Manual collection and delivery save the correct PaymentIntent mapping and do not print at authorisation.
- Capture, transfer, cancellation, automatic collection, and print-only behavior match the production baseline.
- Failed capture produces no success log or capture receipt.
- Modifications and restaurant/receipt metadata survive the full payload path.
- Per-order success/cancel URLs follow the same validation/default behavior, with secret order tokens masked in logs.
- Tests cover manual collection/delivery, legacy delivery, automatic collection, failed capture, print-only, return URLs, and test-only configuration.
- Lambda artifact builds for Linux/amd64; deployment command names only `wrenPayment`.
- Shared production files are not silently changed while adapting Wren.

## Boundaries and follow-up

This phase does not deploy, change API Gateway/Stripe webhook routing, change Lambda timeout, replay events, or capture/refund existing orders. Mock external Stripe, database, printer, and email calls during implementation tests.

The current Stripe test webhook points to `payment`; code synchronisation alone will not repair that routing. After the code change is reviewed, a separate deployment/configuration step must route test webhook processing to the corrected test implementation and validate a fresh order end to end.

The pre-existing shared vet error in `storage/repo.go` formats an integer HTTP status with `%s`. A minimal `%d` correction may be included in Wren to allow normal checks, documented as a shared baseline defect; propose the matching production correction separately rather than editing production as part of this task.

Previously created authorisations lack the new metadata/mappings and need separate reconciliation. Do not treat deployment of the new checkout code as recovery of those orders.
