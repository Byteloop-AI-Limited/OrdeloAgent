# TEST3100 test orders

End-to-end walk-through with fake STRK orders on WhatsApp and Telegram: [live-order-test-harness.md](live-order-test-harness.md).

Implemented in source on 9 October 2026. The owner has run the routing migration. Its revised version removes the unnecessary historical checks and global payment-mode protection artifacts. Service restart/deployment status is separate from database installation.

## Rule

New web and WhatsApp orders use Stripe test only when an accepted item has the exact `product_name` `TEST3100`. Every other new basket uses live payment, including an overwatch customer's basket. There are no restaurant, customer, URL or browser test selectors.

`TEST3100` is a normal priced item. Keep its quantity, price and modifications in normal totals, payment items, restaurant messages and paper receipts. Restaurant staff must not prepare its food. A delivery order containing it is offered only to normally eligible overwatch riders; collection creates no rider dispatch.

## Retained payment and Wren services

The accepted architecture keeps **two payment services**. Ordelo selects the service; neither service is being merged into the other or changed to choose test/live dynamically inside a single endpoint.

Configured base URLs were rechecked on 9 October 2026:

| Environment | Ordelo setting | Configured base URL | Lambda / repository |
| --- | --- | --- | --- |
| Live | `ms_stripe_url` → `ms_settings.stripe_url` | `https://z0hydw9v90.execute-api.eu-west-2.amazonaws.com/prod` | `payment` / sibling `payment-service` |
| Test | `ms_stripe_url_test` → `ms_settings.stripe_url_test` | `https://0af50z1k40.execute-api.eu-west-2.amazonaws.com/prod` | `wrenPayment` / sibling `wren-payment-service` |

The `/prod` stage suffix exists on **both** APIs. The hostname/integration and credentials determine the service environment; the stage name does not make Wren a live payment service. Wren is intended to mirror the payment behaviour using its test Stripe credentials and test payout account.

For every new web or WhatsApp order, delivery or collection, `create_food_order_with_items` saves `payment_mode='test'` if any of that order's accepted items has the exact name `TEST3100`; otherwise it saves `live`. `FoodOrder.payment_uri` appends:

```text
/threads/{thread_id}/orders/{order_id}/payment-url
```

to the selected base. The path uses the short `order_id`, for example `MHZL-32`, rather than the restaurant-prefixed `order_number`.

| New-order example | Service selected |
| --- | --- |
| Ordinary basket, ordinary customer | `payment` (live) |
| Ordinary basket, overwatch customer | `payment` (live) |
| Exact `TEST3100` item, ordinary or overwatch customer | `wrenPayment` (test) |
| Exact `TEST3100` item, anonymous web customer | `wrenPayment` (test) |
| Lowercase/padded/partial name, or marker only in SKU/notes/modifications | `payment` (live) |

The whole order uses the selected service, including its other items and normal fees. Local/test application hostnames do not select Wren. Browser switches and the former restaurant list have no effect. The stored mode selects the endpoint on subsequent operations; the marker is not recalculated to switch an already-created payment's account.

## Which operations use the selected endpoint

| Operation | Ordelo path | Payment-service request |
| --- | --- | --- |
| Delivery checkout | `generate_payment_intent_url` | Manual authorisation, wire action `delivery` |
| Collection checkout | `generate_takeaway_manual_payment_url` | Manual authorisation, wire action `collection` |
| Delivery capture | `delivery_hooks.capture_payment` | `payment_mode='capture'`, at rider assignment |
| Collection capture | `takeaway_hooks.capture_takeaway_payment` | `payment_mode='capture'`, at the finalized pickup-time boundary |
| Cancellation/release | `delivery_hooks.cancel_payment`, also used by collection | `payment_mode='cancel'`; the payload does not need the marker because the order's stored environment selects the service |
| Pay-at-restaurant print job | `generate_automatic_payment_url(..., is_print_only=True)` | `printonlyjob=true`; a receipt operation, not a Stripe payment |

All these requests use the same selected `/payment-url` endpoint. A test checkout therefore continues through Wren for capture/cancellation; a live checkout continues through payment. The frontend displays the backend's reported mode and hosted Checkout URL; it does not choose an API base.

Stripe authorisation webhooks are a separate configured route. They do not obtain their destination from `FoodOrder.payment_uri`. Each selected environment needs a compatible webhook handler and the matching Stripe account so the PaymentIntent mapping used for capture is saved. This documentation review rechecked Ordelo's base settings and source paths; it did not reverify webhook destinations, deployed binary parity or successful provider capture. The [9 October investigation](payment-service-investigation-2026-10-09.md) and [Wren comparison](wren-payment-service-parity-review-2026-10-09.md) record the earlier deployment mismatch as dated evidence.

Source: [FoodOrder routing](../utils_common/order_management/food_order_pymodel.py), [atomic creation RPC](../ordelo_datamodels/jobs_n_functions/create_food_order_with_items.sql), [checkout helpers](../utils_common/payment_ms/payment.py), [delivery operations](../watomation/routers/delivery_hooks.py), and [collection capture](../watomation/routers/takeaway_hooks.py).

## Payment lifetime and dispatch audience

The atomic `create_food_order_with_items` RPC derives and stores `food_order.payment_mode` from its accepted item array, ignoring any supplied mode. The order and items commit or roll back together. `FoodOrder.payment_uri` uses that stored mode throughout checkout, capture, cancellation and print-only handling.

Existing food-order records are not scanned, backfilled or reclassified. Historical orders, including those with NULL payment modes, are not a prerequisite for installing the new-order rule. Newly created orders receive an explicit mode from the creation RPC; an invalid/missing mode on a payment operation remains an application data error, not a requirement to repair historical rows.

Dispatch uses `order_has_test_item(order_number)` and the existing `overwatch_list`. It does not infer marker presence from payment mode, which can differ on legacy payments. SQL filters normally eligible riders before priority/batch ranking, preserving town, vehicle, shift, existing-offer and inflight exclusions. No eligible overwatch riders means the existing no-rider/timeout flow; it never widens to ordinary riders.

The dispatch webhook classifies each order once per batch. The sender and missed-notice helper recheck the actual order and current overwatch membership before sending, covering stale payloads and membership changes. Unknown orders or failed reads suppress sends and report an operational error. Confirmed normal orders require no overwatch read. Operational alerts and sys-admin access continue using overwatch for their existing purposes.

The quoted `payment_mode='capture'` or `'cancel'` in a payment-service HTTP payload chooses an operation, not test versus live. Those existing operation values remain unchanged.

## Cached client compatibility

The frontend no longer reads its former URL/sessionStorage switch or forwards a test request. It displays the backend-derived mode. The web backend temporarily discards an old cached client's retired request field and recognises both old canonical hash forms for the same basket/address/identity. The field cannot select payment mode. Changed baskets or addresses still conflict, and old cached quotes retain their order and payment URL.

## Install or clean up the migration

The supported SQL file is [test3100_order_routing.sql](../ordelo_datamodels/migrations/test3100_order_routing.sql). It has no historical readiness assertion, order backfill, pending-offer cleanup, reconciliation report or global payment-mode protection trigger. It installs/replaces only the marker lookup, item-derived order creation and rider-selection functions, and removes the obsolete configuration setting.

If you already ran the earlier file, run only its first three cleanup statements:

```sql
DROP TRIGGER IF EXISTS food_order_payment_environment_fixed ON public.food_order;
DROP FUNCTION IF EXISTS public.forbid_payment_environment_change();
DROP FUNCTION IF EXISTS public.assert_test_order_cutover_ready();
```

The cleanup is repeatable and does not update/delete food orders or dispatch rows. Otherwise run the whole revised migration once, then restart/deploy the updated services. No older R1/R3 migrations or retrospective order fixes are needed. The owner runs live SQL; editing this file does not apply it.

Verify fresh normal and TEST3100 orders. New payment environments come from their accepted items. Check Wren's checkout/capture and webhook account alignment separately; no AWS or Stripe configuration is changed by this migration.

## Read-only verification

```sql
SELECT fo.order_number, fo.payment_mode, fo.payment_status,
       public.order_has_test_item(fo.order_number) AS has_test_item
FROM public.food_order fo
WHERE fo.order_number IN ('<ordinary-order>', '<marker-order>');

SELECT product_name, quantity, price, modifications
FROM public.order_item WHERE order_id = '<marker-order-id>';

SELECT * FROM public.get_available_riders('<marker-order>', '<town>', '<vehicle>');

SELECT order_number, rider_id, status
FROM public.delivery_dispatch WHERE order_number = '<marker-order>';
```

Candidate eligibility queries are read-only. Do not invoke scheduled dispatch or cancellation functions against the live database merely to check the migration.

## Validation

Backend regression coverage includes new-order environment snapshots, marker-scoped rider audiences, refreshed membership, stale dispatch/missed payloads, and legacy checkout hash comparisons that reject changed baskets/addresses.

The SQL regression runs actual functions in an isolated embedded PostgreSQL engine. It checks all four creation definitions, marker exactness, caller-mode rejection, retained receipt items, atomic rollback, unchanged historical rows, removal of obsolete artifacts, normal and restricted candidates before batching, and the actual pre-pickup cancellation/redispatch function. It makes no live database or HTTP calls.

To repeat the SQL test, install the pinned development dependency outside the application, then run:

```sh
npm install --prefix /private/tmp/ordelo-test3100-sql --no-audit --no-fund --ignore-scripts @electric-sql/pglite@0.5.8
node tests/ordelo_datamodels/test_test3100_sql.mjs /private/tmp/ordelo-test3100-sql/node_modules/@electric-sql/pglite/dist/index.js
```

Use the usual prepared Python shell for `python -m pytest -q`. Frontend checks are `npx tsc --noEmit`, `npm run lint`, `npm run build`, and `node scripts/test-test-orders.cjs`. See the [design plan](../plans/test3100-payment-routing-plan.md) and [ADR 0010](adr/0010-test-payments-selected-by-order-items.md) for decisions and scope.
