# Ordelo payment endpoint check — 9 October 2026

> Historical investigation before the TEST3100 redesign. Its former restaurant/customer selection rules are superseded. The retained live/Wren endpoint mapping and current item-only selection are documented in [test-orders.md](test-orders.md#retained-payment-and-wren-services). This report's observations describe the orders and runtime inspected at that time.

## Finding

OrdeloAgent is calling the intended Wren/test payment endpoint for the two orders discussed in the shared chat. No wrong checkout/capture endpoint was found in `FoodOrder.payment_uri` for these orders.

The webhook gateway discussed in the earlier investigation still targets the production `payment` Lambda. The Wren API currently exposes only its checkout/capture route, without a webhook route. Those are separate routing concerns from Ordelo's payment URL selection.

## Scope and evidence

Read the shared chat titled **Outdated Wren Payment Service**:
https://chatgpt.com/s/cx_6ac8ce04744c819188153cf75a6a853c

Inspected current OrdeloAgent source, payment-service's request dispatcher, and Wren's current source/build target. Read the current AWS-backed Ordelo payment URL settings, the two affected database records, and AWS API Gateway integrations and request mappings. No payment requests, database writes, deployment changes, or configuration changes were made.

## Current configured bases and AWS targets

| Setting / API | Current value / route | Lambda target |
| --- | --- | --- |
| `ms_stripe_url` | `https://z0hydw9v90.execute-api.eu-west-2.amazonaws.com/prod` | `payment` |
| `ms_stripe_url_test` | `https://0af50z1k40.execute-api.eu-west-2.amazonaws.com/prod` | `wrenPayment` |
| Webhook API `hjgttc1wpj` | `POST /webhook/{webhookID}` | `payment` |

Both checkout APIs expose `POST /threads/{threadID}/orders/{orderID}/payment-url`. AWS maps the path identifiers into `querystring.threadID` and `querystring.orderID`, matching the payment handler's parameter reads. The `/prod` stage name on the Wren API does not make it the production payment service; its integration target is `wrenPayment`.

The Wren API route listing contains no `POST /webhook/{webhookID}` route. The webhook gateway's integration was verified now; Stripe's currently configured webhook destinations were not independently re-read in this check. The shared chat records Stripe test events using that gateway.

## Affected orders

| Order | Stored action | Stored payment mode | Current Ordelo payment status | Resolved API |
| --- | --- | --- | --- | --- |
| `ELAS-UGMK-29` | `takeaway` | `test` | `requires_capture` | `0af50z1k40` → `wrenPayment` |
| `ELAS-YPYH-27` | `takeaway` | `test` | `requires_capture` | `0af50z1k40` → `wrenPayment` |

For UGMK-29 the resolved URL is:

```text
https://0af50z1k40.execute-api.eu-west-2.amazonaws.com/prod/threads/WEB-110eff3a-f99e-4390-9fdf-14f225ceeba6/orders/UGMK-29/payment-url
```

This matches the capture URL in the shared chat's logs. The short `order_id` is correct for this payment-service contract. Current Ordelo status is database evidence; Stripe's current capture state was not rechecked here.

## Source trace

- `utils_common/order_management/food_order_pymodel.py:196`: explicit `payment_mode='test'` selects test; explicit `live` selects live; otherwise only an overwatch delivery selects test.
- `utils_common/order_management/food_order_pymodel.py:209`: `payment_uri` appends the same thread/order/payment-url path to the selected base.
- `utils_common/payment_ms/payment.py`: checkout creation uses `food_order.payment_uri` for both delivery and collection helpers.
- `watomation/routers/takeaway_hooks.py:430`: capture reloads the persisted order and uses that same property. Its payload sets `payment_mode='capture'` to dispatch the operation inside payment-service.
- `utils_common/web_ordering/web_checkout.py:401` and `ordelo_datamodels/jobs_n_functions/create_food_order_with_items.sql:35`: web order creation persists the test/live mode.
- `FoodOrder.from_order_number` selects all stored columns and constructs `FoodOrder` directly. `exclude=True` on `payment_mode` affects serialization, not reading the stored field.
- Payment-service's `Handler.Generic` handles capture and cancel on the existing `/payment-url` route. A dedicated `/capture` endpoint is not required by this contract.

Do not confuse the two meanings of `payment_mode`: the database model uses `test`/`live` to choose the service; the HTTP capture payload uses `capture` to choose the operation.

## Edge case and limits

A collection order with no stored mode uses the live base, even for an overwatch recipient. This is documented fallback behavior and is covered by existing tests; it does not explain these two orders, which explicitly store `test`. Local startup, a test hostname, or `action='takeaway'` alone does not force test payments.

Settings were freshly loaded from the application's AWS secret. A previously started service process can retain older settings; for UGMK-29, the historical request log independently agrees with the currently loaded URL.

Wren's local source now includes a test-key runtime check, and its buildspec targets `wrenPayment`. These local facts do not establish that the synchronized implementation has been deployed. Deployment artifact parity and current Stripe destination configuration remain separate checks.

## Validation

Ran the existing focused suites for FoodOrder, payment-mode resolution, checkout payloads, and collection capture/retries: **31 passed**. These use mocked configuration and HTTP; live AWS and database reads above provide the independent endpoint evidence.

No Ordelo endpoint code change is indicated for these affected orders. Complete the Wren deployment and webhook alignment described in the separate service plan, then verify a fresh end-to-end order.
