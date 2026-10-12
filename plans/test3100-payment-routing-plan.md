# TEST3100-only payment and rider dispatch routing

Date: 9 October 2026. Status: approved and implemented in source. The owner ran the migration. Its revised version removes historical checks and the optional global mode-protection artifacts. Deployment and provider verification remain separate steps. The sections below retain the design rationale; see docs/test-orders.md for current operation.

## Agreed outcome

For every newly created order, across WhatsApp and web, delivery and collection:

```text
Any accepted item in THIS order has product_name exactly "TEST3100"
    → Stripe test service for the whole order
    → Delivery offers restricted to eligible overwatch riders
Otherwise
    → Stripe live service for the whole order
    → Normal eligible rider pool, including when the customer is in overwatch
```

No restaurant allowlist, overwatch eligibility, hostname, browser toggle or additional test-permission check participates. A public web checkout follows this same rule. Existing ordering validation continues to apply to the basket.

The owner confirmed:

1. The selection rule applies to newly created orders. The owner explicitly rejected retrospective repair, scanning or backfilling of historical food orders.
2. `TEST3100` stays a normal priced item. It contributes to the normal total and remains in the basket, payment line items, restaurant messages and paper receipt. Its presence tells restaurant staff that the order is for testing and must not be prepared.

## Precise matching and lifetime

- Match `product_name`, not SKU, notes, modifications, a URL parameter or a customer number.
- Match exactly `TEST3100`. Lowercase, whitespace-padded names and names containing it as a substring do not match. Existing valid-item quantity rules apply; there is no new quantity or price gate.
- Only inspect items belonging to the order being created. A test item on another order never affects it.
- One matching item selects test for the entire order, including other items and fees.
- Once the order is persisted, its accepted items and payment environment form the payment snapshot. Checkout retries, later capture, cancellation and print-only handling retain that environment. Adding or removing an item would require a new order; raw database item edits must not switch an existing Stripe payment's account.
- The stored `food_order.payment_mode` remains as the result of item selection and as the record of existing payment routing. It is not an input toggle or an eligibility gate.

## What the current implementation does

The live investigation of `ELAS-MHZL-32` found `payment_mode='test'`, a non-overwatch recipient, and a request to Wren. The creation log gave `reason=test_restaurant`. The configured restaurant list included ELAS.

Current backend selection is split between `resolve_payment_mode()` and `FoodOrder.uses_test_payment`: the former checks the restaurant list and requested-test/overwatch eligibility; the latter also falls back to overwatch delivery when the stored mode is null.

Both current order creation flows use `create_food_order_with_items(p_order,p_items)` to persist the order and its item rows atomically. WhatsApp creates through `order_service`; web checkout calls that RPC from its locked transaction. Both reload `FoodOrder` before generating payment URLs.

The frontend has a query/sessionStorage toggle, forwards a test request in two checkout flows, and simulates restaurant eligibility in fixtures. It already renders the test label from the backend's returned `payment_mode`.

## Design: derive once from accepted items, retain the result

Use the existing atomic order-creation RPC as the authoritative place to derive the environment. Its accepted `p_items` become this order's `order_item` rows in the same transaction. Compute:

```sql
CASE WHEN EXISTS (
    SELECT 1
    FROM jsonb_array_elements(p_items) AS item
    WHERE item->>'product_name' = 'TEST3100'
) THEN 'test' ELSE 'live' END
```

Persist that explicit value in `food_order.payment_mode` for every new order. Ignore any caller-supplied environment in `p_order`; the order's items are the authority. Preserve all current RPC columns, validation, item insertion, idempotency information and transaction behaviour.

`FoodOrder.uses_test_payment` then reads the fixed mode and `payment_uri` selects the existing test/live base. Delete its overwatch fallback. Do not add a database lookup to each property access: that would allow item mutations to reroute an existing authorisation and would duplicate the item reads already used to build payment payloads.

An order-item audit equivalent to the owner's query must always include the order identifier:

```sql
SELECT product_name, quantity, price, modifications
FROM order_item
WHERE order_id = '<this-order-id>'
  AND product_name = 'TEST3100';
```

The existing item-summary selects keep returning all items. Do not filter the marker out of the payment or receipt. Item/database failures remain operational errors; do not turn a failed read into a guessed payment environment.

## Backend changes

| File / area | Planned change |
| --- | --- |
| `ordelo_datamodels/jobs_n_functions/create_food_order_with_items.sql` | Derive and persist test/live from `p_items`, retaining the existing atomic insert contract. |
| New deployment migration | Install the same final RPC definition and provide definition verification; do not inspect/backfill historical orders. No new test flag, allowlist or environment column. |
| Existing SQL copies of the RPC | Align bootstrap/replay definitions so a later schema rebuild cannot restore client-controlled selection. Inventory includes `ordelo_agg_r1_test_payment.sql` and `ordelo_agg_r3.sql`; inspect every definition before updating. |
| `utils_common/order_management/food_order_pymodel.py` | Use persisted mode; remove payment-specific overwatch lookup and fallback; update the docstring. Retain `exclude=True` for restaurant-app serialization. |
| `utils_common/payment_ms/payment_mode.py` | Remove the existing eligibility resolver and its callers. No replacement gate is needed. |
| `config/feature_flags.py` | Remove the retired payment-list constant/comment. `config_csv` currently has no other production caller; remove its unused CSV cache/helper after a complete caller check. Keep helpers required by emergency ordering pause and return-URL configuration. |
| `watomation/routers/order_hooks.py` | Remove requested-test selection and the request toggle; create through the item-derived RPC and report the reloaded order's mode. |
| `utils_common/order_management/order_service.py` | Remove caller-selectable `payment_mode` and its eligibility validation; let the RPC select the mode from the items. |
| `utils_common/web_ordering/web_checkout.py` | Remove test-request/restaurant selection and `test_payment_not_allowed`; retain the existing durable order, quote, access and idempotency workflow. |
| Payment creation, delivery/collection capture and cancellation | Continue using the same order's stored mode. Audit all existing callers so none selects an environment from customer identity or payload operation. |

The HTTP payload's `payment_mode='capture'` or `'cancel'` selects an operation inside payment-service. Keep those values: they are different from the order's stored `test`/`live` environment.

The unused legacy `insert_wa_order` helper is not called by the current runtime. Check repository references and either retire it or route any supported use through the atomic RPC so it cannot create new orders with unresolved payment environments.

## Rider dispatch extension — 9 October 2026

The owner extended the design: the same exact `TEST3100` item identifies an order whose delivery offers must go only to overwatch riders. The ordering customer's membership in overwatch must no longer determine that restriction. This applies to both WhatsApp and web delivery orders; collection does not create a rider dispatch.

### Verified current behaviour

`watomation/routers/delivery_hooks.py`, `delivery_dispatch_hook` (currently lines 429–476), checks whether `customer_id` belongs to `overwatch_list`. If it does, it sends only when `rider_id == customer_id`. It does **not** allow all overwatch riders. For customers outside overwatch it schedules every dispatch in the payload. Its current skip log also runs after the permitted self-dispatch, so the permitted message is misleadingly logged as skipped.

Read-only inspection of the deployed database on 9 October confirmed that `get_available_riders`, `job_create_dispatch`, `delivery_dispatch_whook_statement` and `notify_missed_dispatches` agree with the checked-in functions inspected for this proposal:

- `get_available_riders` selects by town, vehicle type and on-shift status, excluding riders already offered this order or currently inflight. There is no test-order/overwatch restriction in that function.
- `job_create_dispatch` applies priority and vehicle batch size to those candidates, then inserts dispatch rows. The customer-based restriction runs later, in Python, after those rows exist.
- The dispatch trigger payload includes `order_number`, `rider_id` and `customer_id` but contains neither item names nor a test-order classification.
- `notify_missed_dispatches_hook` schedules its rider message for every supplied dispatch; it has no corresponding test restriction. The current deployed producer selects accepted dispatches for an assigned order. This is a path to cover for stale/legacy payloads, not evidence that every initially suppressed dispatch has received a missed message.

### Proposed recipient rule

```text
if this order contains an exact TEST3100 item:
    candidates = normally eligible riders ∩ overwatch members
else:
    candidates = normally eligible riders
```

An overwatch member must also be a rider with the existing town, vehicle, shift and availability eligibility. Keep priority, batch size, previous-offer exclusions and inflight exclusions. “Overwatch riders” means that intersection; it does not mean every operations contact, forced shift availability or a broadcast to the whole list.

Examples:

| Customer / order | Rider dispatch result |
| --- | --- |
| Ordinary customer with marker | Only eligible overwatch riders |
| Anonymous web customer with marker | Only eligible overwatch riders; no phone equality needed |
| Overwatch customer with marker | Eligible overwatch riders, including another overwatch rider |
| Overwatch customer without marker | Normal eligible rider pool |
| Ordinary customer without marker | Normal eligible rider pool |
| Marker, no eligible overwatch riders | Existing no-rider/timeout path; never widen to ordinary riders |

### Implementation proposal

1. **Share the marker meaning.** Use an order-scoped predicate with the same exact equality as payment selection. For dispatch, resolve `order_number` to `food_order.order_id`, then test `order_item.product_name='TEST3100'` for that order. A small read-only SQL helper can expose this predicate to rider selection and the webhook. Keep the RPC's creation-time payment derivation semantically identical. Do not infer dispatch restrictions solely from `payment_mode='test'`: preserved old payments may use test without a marker, and preserved old live payments may contain one.
2. **Filter before dispatch insertion.** Extend `get_available_riders` in `ordelo_datamodels/jobs_n_functions/job_create_dispatch.sql`: when the scoped marker predicate is true, add the rider-membership condition using existing `ordelo_config.overwatch_list`. Apply this before `job_create_dispatch` ranks and batches candidates, so ordinary riders cannot consume batch slots or acquire dispatch rows for new test orders. Parse the comma list with the same trimming semantics as `get_overwatch_list`; do not introduce a second audience list.
3. **Retain a message guard.** Replace the customer/self check in `delivery_dispatch_hook` with marker plus rider-membership checks. Resolve each distinct order once per batch and load overwatch membership once rather than per dispatch. The trigger must either include the authoritative classification or the handler must retrieve it; do not guess from `customer_id`. Recheck membership immediately before sending in the background task to handle membership changes between the database job and message send.
4. **Cover later dispatch messages.** Apply the same audience predicate to missed-dispatch messages for restricted orders, including stale payloads. Continue the existing bookkeeping updates so suppressed rows are not repeatedly reconsidered. Inventory other dispatch-message entry points and manual synthetic payload scripts for the same rule.
5. **Keep redispatch restricted.** Pre-pickup cancellation reopens the order and clears competing rows. Because candidates come through the updated `get_available_riders`, subsequent rounds remain overwatch-only; the declining rider remains excluded as today. Exhausted overwatch candidates must not fall back to normal riders.
6. **Handle missing information explicitly.** An empty/missing overwatch list gives no test-order candidates. Failed marker or membership reads suppress test-uncertain sends and report the operational failure; they must not cause unrestricted fan-out. Missing order mapping must be distinguished from a confirmed order without a marker. Normal orders should not require a successful overwatch lookup to be dispatched.
7. **Correct diagnostics.** Log `test_order` classification, scheduling versus suppression, and reasons such as `test_order_non_overwatch_rider`. Keep customer numbers and addresses out of new diagnostics. Scheduling is not confirmed WhatsApp delivery. Fix the current allowed-self-then-skipped log as part of replacing that branch.

This keeps the existing `overwatch_list` as an operational recipient audience. It removes customer identity as the trigger for test dispatch isolation; it does not remove operations membership itself.

### Dispatch cutover and acceptance

The owner clarified that historical orders and dispatch records do not need retrospective cleanup. Install the new dispatch functions without a historical readiness gate or modifying old assignments/offers.

Add focused tests for mixed batches containing several orders, ordinary and overwatch customers, a different eligible overwatch rider, web W-ids, exact-name variants, a marker on a different order, empty membership, read failures, stale non-overwatch payloads and missed notifications. Verify no background send is scheduled for a blocked rider, while a normal order still uses its normal pool.

Use isolated database tests to verify filtering occurs before priority/batch selection, in-shift and inflight exclusions remain, and pre-pickup cancellation never expands a test order's audience. After deployment, read the candidate results and dispatch rows for a fresh marker order and a normal order before any live messaging test. Verify the marker order has no ordinary-rider dispatch rows. No live dispatch, rider setting or database function has been changed during this planning investigation.

## Frontend changes

Apply to `/Users/basavaraj/bloop/restaurant-frontend` after implementation is authorized:

| File / area | Planned change |
| --- | --- |
| `lib/testPayment.ts` | Delete query and sessionStorage selection. Existing saved browser values have no consumer. |
| `components/BasketDrawer.tsx` | Remove the helper import and `testPayment` request field; retain ordinary `TEST3100` basket line serialization. |
| `components/ordelo/OrdeloMenuContainer.tsx` | Remove the effect that remembers the query switch. |
| `components/ordelo/CheckoutFlow.tsx` | Remove test-request construction; keep the backend-derived test label. |
| `app/api/checkout/route.ts` | Remove test request forwarding and test-request diagnostics. Keep returned `payment_mode` and normal checkout behaviour. |
| `app/api/web/orders/route.ts` | Stop forwarding a test request. Continue forwarding the accepted item names, quantities, prices and modifications. |
| `lib/web/types.ts` | Remove the request toggle; retain the quote's test/live result. |
| `lib/web/fixtures/index.ts` | Remove the fixture restaurant test list. Derive simulated quote mode from an exact matching basket item at any restaurant. |
| `app/order-summary/page.tsx` | Update the mode comment; retain test-mode notice from the backend result. |
| `GLOSSARY.md` and relevant documentation | Mirror the agreed test-order, test-item and payment vocabulary. |

Web ordering continues to use its live backend in the live environment. Existing offline fixtures are development tools, not test-payment eligibility gates; their simulated payment page must remain clearly identified as simulation.

Do not introduce a marker-insertion button, hide the item, change its menu price, or add a permission gate. The existing menu/basket workflow supplies it like any other product.

## New-order installation and cleanup

There is no retrospective fix, backfill, historical payment review or old pending-offer cleanup. The revised migration leaves existing order and dispatch rows untouched and never blocks installation on their status or stored mode.

The owner already ran the original statements. Run only the three DROP statements at the start of the revised migration to remove the readiness helper and the optional global payment-mode protection trigger/function. Required marker, order-creation and rider-selection functions remain. The whole revised migration is also repeatable for a fresh install or reinstall.

Also preserve existing web quotes and idempotency behaviour. Removing a request field changes the current `fingerprint(req, address)` input, so existing hashes must be handled deliberately. Keep a narrow read-only comparison against the legacy canonical request shape for pre-cutover attempts, or migrate those hashes from verified request data. It must only recognise the same basket/address and return the same old order/URL; it must never use a retired field to select the service. Include changed-basket conflict tests. Do not solve this by clearing existing idempotency rows or creating replacement orders automatically.

## Repository-wide cleanup

The requested retired key is `retired restaurant-wide payment switch`. Remove its executable use and literal references from both repositories as part of implementation. This includes comments, fixtures, active guides, historical plan/release prose, SQL examples, raw configuration exports, the local automatic-order skill's references, and this proposal after its cleanup inventory has served its purpose. Preserve historical meaning with wording such as “the retired restaurant-wide payment switch” rather than leaving executable restore instructions.

Current inventory includes:

- `notebooks/db_queries/{CommonQueries,config_updates,adhoc_queries,ordelo-agg-db-switch}.sql`.
- `notebooks/db_queries/restaurant_queries/onboarding_crms/{00_preflight_readonly,03_prod_test_enable,04_go_live,99_rollback}.sql` and `result_export.json`.
- `.claude/skills/ordelo-local-automatic-orders/references/{test-enable,production-restore}.sql`, `configuration.md` and `workflow.md`.
- `docs/onboarding-web-only-restaurant.md`, `docs/web-ordering-playground.md` and its HTML companion.
- Older release notes and plans including `ordelo-agg-plan-cc.md`, onboarding and payment-return plans; update supersession context without presenting the new rule as historical implementation.
- Existing order hooks/payment-mode tests and frontend fixture documentation/comments.

Run a fresh repository-wide search at implementation time, including hidden skill files and HTML, rather than treating this list as exhaustive. Do not modify `.git` history, dependencies or unrelated local work. Current notebook edits are user work and need careful patching around their changes.

Delete the retired browser selector and test-request forwarding from production paths. Overwatch still exists for operations alerts and as the restricted test-dispatch audience. Remove the ordering customer's overwatch membership as a trigger for payment or dispatch testing.

## Validation and acceptance

| Scenario | Expected outcome for a new order |
| --- | --- |
| Ordinary customer, ordinary basket, any restaurant | Live |
| Overwatch customer, ordinary basket | Live |
| Basket contains exact `TEST3100`, ordinary customer | Test |
| Basket contains exact `TEST3100`, anonymous web customer | Test |
| Basket contains exact `TEST3100`, any restaurant | Test |
| Lowercase, padded or substring product name | Live |
| Matching marker appears only on another order | Live |
| Notes, modifications or SKU mention the marker; product name does not | Live |
| Old URL/browser switch, no marker | Cannot select test |
| Marker mixed with ordinary products | Entire order test; all lines and normal fees retained |
| Repeated checkout request | Same order, mode and cached URL |
| Delivery assignment, collection pickup-time capture, cancellation | Same service used for that order's checkout |
| Preserved pre-cutover test payment without marker | Remains test for its existing payment lifetime |
| Preserved pre-cutover live payment with marker | Remains live for its existing payment lifetime |

Validation work:

1. Exercise the actual RPC on an isolated database for exact match, non-match, cross-order isolation, atomic rollback and rejection of caller-selected modes. Test all deploy/bootstrap copies against the intended final definition.
2. Update backend tests for FoodOrder, order creation, payment helpers, web contracts, delivery/collection capture and cancellation. Use mocks for external effects; verify the selected base URL and operation payload together.
3. Cover a non-overwatch normal order at ELAS as the regression for this incident; also cover ordinary overwatch delivery so the removed fallback cannot return.
4. Test that migration leaves historical rows, including NULL modes, unchanged; verify artifact removal plus cached quote and idempotency compatibility.
5. Frontend: run type checking, lint and the production build; smoke-test both checkout flows with and without the marker, stale URL/sessionStorage values, backend-derived notices and unchanged pay-at-restaurant behaviour.
6. Verify item price/quantity and ordinary products are retained in checkout totals, payloads, restaurant notices and rendered receipts. Inspect a real test receipt for visible `TEST3100` and staff recognition.
7. Search both repos for the retired key and active legacy selectors. No runtime payment eligibility gate or fixture restaurant list should remain.
8. After deployment, create fresh marker orders for delivery and collection; verify test checkout, saved PaymentIntent mapping, later capture/cancel and visible receipt marker. Verify normal new orders select the live endpoint without completing a real payment unless separately authorized.

Do not substitute mocked tests for service verification. Wren and Stripe's webhook must process the same test account; the earlier missing webhook route/account mismatch is a separate deployment dependency. This plan simplifies Ordelo selection and does not silently repair AWS or Stripe routing.

## Deliverables and review boundary

- Backend and frontend changes implementing the item-only selector and removing obsolete controls.
- A new-order-only migration plus repeatable removal of previously installed optional artifacts; no historical order writes.
- Updated focused regressions and frontend checks.
- Updated database rider-candidate filtering and dispatch/missed-message guards, with isolated eligibility and redispatch checks.
- Updated payment flow, local testing, onboarding and playground documentation; paired HTML/Markdown guides stay consistent.
- ADR 0010 and both glossaries recording test payments and the receipt's meaning.
- A deployment checklist with current Wren/webhook verification and post-deploy evidence.

The owner authorized implementation. Both repositories now contain the item-only policy, SQL and regression coverage. The owner ran the SQL. Apply only the cleanup statements from the revised file if the old optional artifacts remain, and restart/deploy the services separately. This file edit does not execute live SQL.
