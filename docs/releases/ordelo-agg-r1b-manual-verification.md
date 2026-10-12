> Historical design/verification snapshot. Payment testing was superseded on 9 October 2026: new orders use test only with an exact `TEST3100` item, and test delivery offers are restricted to eligible overwatch riders. See the current test-orders guide.

# R1b and R2: manual verification guide

Use this with [the implementation notes](/Users/basavaraj/bloop/OrdeloAgent/docs/releases/ordelo-agg-r1b-2026-10-02.md), [the plan](/Users/basavaraj/bloop/OrdeloAgent/plans/ordelo-agg-plan-cc.md) (§18 and §22), and [the local testing runbook](/Users/basavaraj/bloop/OrdeloAgent/docs/local-testing-runbook.md).

R1b is implemented in the local checkout. Deployment, the BNAT customer-message comparison, and the actual R2 Stripe test remain pending. The previous verification left shared configuration unchanged. Re-read configuration before starting; the observations in the implementation notes are a snapshot.

Steps 1–3 explain the change and run isolated checks. Steps 4–14 exercise shared services during a maintenance window. No schema migration is needed: the configuration statements below change existing settings only.

## 1. Understand the new route

With the notifier disabled, the hooks retain their legacy behavior. With it enabled for BNAT, an order notification follows:

```text
hook → customer event → subscription → outbox → channel adapter

WhatsApp order → whatsapp_restaurant → original restaurant webhook
Web order     → web_page             → record event, no external send
```

- `order_customer_event` records what happened to the order.
- `order_notification_subscription` identifies its notification channel.
- `notification_outbox` records whether that event was sent, skipped, or failed.
- Event keys prevent the same order event from being recorded and sent twice. Rider assignments and pickup times have keys that distinguish genuinely new assignments/times.
- Restaurant requests preserve the old URL, JSON body bytes, and redirect behavior. A failed or uncertain HTTP attempt is not retried. The 60-second sweep recovers only committed rows that have never been attempted.
- Web events currently have no visible customer status page; that comes in R3. `skipped` on `web_page` is expected.
- Address capture/update happens before an order exists. These two hooks use the shared address helper and do not create order-event/outbox rows. W-ids are skipped.

Read [customer_notifier.py](/Users/basavaraj/bloop/OrdeloAgent/utils_common/notify/customer_notifier.py) in this order: `enabled_for`, `notify_address`, `_record`, `_claim`, `dispatch`, `publish`, `sweep_pending`. Read [feature_flags.py](/Users/basavaraj/bloop/OrdeloAgent/config/feature_flags.py) for the settings/cache.

## 2. See which ten hooks changed

| Hook / source | Customer event or action |
| --- | --- |
| `payment_hooks.handle_payment_complete` | `payment_authorised` |
| `order_hooks.capture_address` | Pre-order address notification |
| `customer_hooks.update_address` | Pre-order address notification |
| `takeaway_hooks._post_pickup_time_event` | `pickup_time_set` |
| `location_hooks.notify_rider_location_event` — customer arrival | `rider_near_customer` |
| `delivery_hooks.post_rider_event_inflight` | `rider_assigned` |
| `delivery_hooks.post_delivery_timedout` | `no_rider_found` |
| `agent_app_handlers.post_rider_event_customer_cc` | `delivered` |
| `agent_app_handlers.post_rider_event_restaurant_cc` | `food_collected` |
| `on_callback_wa_handler.admin_takeaway_ready` | `ready_for_collection` |

The web branch of payment authorization also publishes `payment_authorised` through the notifier. A payment replay does not schedule publication or summary initialization again.

An additional prerequisite repair wires the already-planned `test_payment` request through create-order. The returned `payment_mode` tells you whether the request was actually honored; requesting test mode alone is insufficient.

## 3. Run the isolated checks first

Open a fresh zsh terminal and prepare it as the runbook requires:

```zsh
cd /Users/basavaraj/bloop/OrdeloAgent
source ~/.zsh_functions
if [[ -d venv ]]; then
    source venv/bin/activate
elif [[ -d .venv ]]; then
    source .venv/bin/activate
else
    echo 'No virtual environment: follow the local testing runbook first.'
fi
export PYTHONPATH="$PWD"
envLoad
```

Proceed only with an activated environment. Run:

```zsh
python -m pytest -q \
  tests/watomation/test_customer_notification_contracts.py \
  tests/utils_common/test_customer_notifier.py \
  tests/watomation/routers/test_payment_hooks.py \
  tests/utils_common/order_management/test_order_service.py
```

Expected: all selected tests pass. These tests fake service dependencies; they do not place BNAT orders or make Stripe payments.

To understand the contract check, open [the contract tests](/Users/basavaraj/bloop/OrdeloAgent/tests/watomation/test_customer_notification_contracts.py) and [their frozen JSON](/Users/basavaraj/bloop/OrdeloAgent/tests/watomation/customer_notification_contracts.json). Each of the ten hooks runs with notifier off/WhatsApp, on/WhatsApp, and on/web. The first two match the original requests; the third makes no restaurant-app request.

The separate notifier tests cover channel isolation, flag scope, failed sends without retries, and recovery of unattempted rows. These are the practical way to exercise all ten hooks without manually driving every rider/location transition.

The last full-suite run had 479 passes and one confirmed pre-existing failure, `test_restaurant_master_get_admins_fetches_live_column`. This is distinct from the selected R1b checks above.

## 4. Save the original shared settings

Before any shared-service test, agree the BNAT maintenance window and coordinate the restaurant/admin and intended test rider. Test orders still create shared jobs and can send rider/admin messages. The payment service can print a kitchen ticket on capture, independently of the restaurant-app customer notification hooks.

In the Supabase SQL editor, read and save these rows, including which keys are absent:

```sql
SELECT config_key, config_value
FROM ordelo_config
WHERE config_key IN (
  'ORDELO_APP_URL', 'RESTAURANT_MENU_APP_URL', 'BNAT_APP_URL',
  'CUSTOMER_NOTIFIER_ENABLED', 'CUSTOMER_NOTIFIER_REST_REFS',
  'PAYMENT_INBOX_ENABLED', 'ORDER_CREATE_RPC_ENABLED',
  'retired restaurant-wide payment switch', 'ENABLE_PAYMENT_TEST_ROUTES'
)
ORDER BY config_key;
```

Check that `PAYMENT_INBOX_ENABLED` is true, and BNAT is permitted by `retired restaurant-wide payment switch`. The existing R1a tables/RPCs must already be installed. An absent notifier flag means off. Do not change unrelated flags as part of this guide.

**Actual shared impact:** changing the two service URLs below changes what production consumers of this database read too. Perform that switch only within the maintenance window, and restore the saved values afterward.

## 5. Start services, logs, and tunnel

Reuse an already-running service on its port, or restart it deliberately; do not start competing copies.

In the prepared OrdeloAgent terminal:

```zsh
uv run --active watomation/fapp_ordelo_agent.py 2>&1 | tee /private/tmp/ordelo-r1b-manual-service.log
```

In a second terminal:

```zsh
cd /Users/basavaraj/bloop/restaurant-frontend
npm run dev 2>&1 | tee /private/tmp/ordelo-r1b-manual-frontend.log
```

Check [local API docs](http://localhost:3100/docs) and [local BNAT menu](http://localhost:3000/restaurant/bnat). Reuse the configured Cloudflare tunnel if running; otherwise start it using runbook §4. Check:

- [Tunnel API docs](https://rider-agent-test.ordelo.app/docs).
- [Tunnel BNAT menu](https://restaurant-test.ordelo.app/restaurant/bnat).

The separate backend on 3101 is not started by these commands. Ensure any backend needed for the existing WhatsApp baseline is available through its established route.

During the maintenance window, switch the two existing URL rows:

```sql
BEGIN;
UPDATE ordelo_config
SET config_value = 'https://rider-agent-test.ordelo.app', updated_at = now()
WHERE config_key = 'ORDELO_APP_URL';
UPDATE ordelo_config
SET config_value = 'https://restaurant-test.ordelo.app', updated_at = now()
WHERE config_key = 'RESTAURANT_MENU_APP_URL';
COMMIT;
```

Re-read both values. Restart local services after the switch. The frontend caches its backend URL for 60 seconds; Ordelo dashboard URLs have a one-hour cache. Account for affected production consumers' caches too, as the runbook describes.

**Before paying:** inspect the Stripe test account's event destinations. `checkout.session.completed` must reach both the payment service and the Ordelo endpoint running this R1b code. Record the endpoint URL and subscribed events for each account in scope. Changing `ordelo_config` does not change a registered Stripe webhook or a Meta callback URL. Verify that DB-triggered hooks and rider/admin callbacks also reach the intended running service; a menu loading successfully does not prove this routing. Stop before creating a web paid order if its later hooks can still reach an older production build.

## 6. Capture a WhatsApp baseline with the notifier off

Keep the notifier off for this baseline. If it was already on when you read the settings, record that first and temporarily set it off for the comparison; restore its original setting in step 14.

```sql
UPDATE ordelo_config
SET config_value = 'false', updated_at = now()
WHERE config_key = 'CUSTOMER_NOTIFIER_ENABLED';
```

If the row was absent, this updates nothing and it remains off. Restart the service or allow its flag cache to expire before the baseline.

Use the intended test customer's normal BNAT WhatsApp menu link, retaining its `recipient` and `thread_id` parameters. Add `isTest3100=true` with `&` when the link already has a query string. Run one delivery and one takeaway through the existing flow, using only confirmed Stripe test mode for any online payment.

Record screenshots/text/timing for customer messages at payment authorization, rider assignment, collection, nearby arrival, delivery completion, pickup time, and ready-for-collection. A separate delivery that receives no rider covers the timeout message. Use the existing address-edit flow to check address updates if exposed. Note which transitions you actually exercised; the contract tests cover the remaining hooks.

Record each `order_id`, `order_number`, and test customer. With the notifier off, new events from these hooks should not create notifier-table rows. This baseline checks customer behavior, not the later web path.

## 7. Enable the notifier for BNAT and repeat the WhatsApp comparison

Set the scope and flag together:

```sql
BEGIN;
INSERT INTO ordelo_config (config_key, config_value)
VALUES
  ('CUSTOMER_NOTIFIER_REST_REFS', 'BNAT'),
  ('CUSTOMER_NOTIFIER_ENABLED', 'true')
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value, updated_at = now();
COMMIT;
```

An empty/missing scope with the flag on enables all restaurants. Keep it explicitly `BNAT` for this pilot. Restart the local Ordelo service, or wait for the 60-second feature-flag cache. `/internal/cache/reset` does not clear these flag caches.

Repeat the delivery and takeaway with new orders, the same test customer, and the same actions. Compare messages to step 6: content, links, ordering, and number of messages should remain unchanged. Record any timing difference rather than assuming timing is identical.

Use this query throughout the rest of the guide, replacing `YOUR_ORDER_NUMBER` with one recorded order number:

```sql
SELECT e.id AS event_id, e.event_key, e.event_type, e.occurred_at,
       s.channel, s.destination, s.active,
       o.id AS outbox_id, o.status, o.attempts, o.last_error
FROM order_customer_event e
LEFT JOIN notification_outbox o ON o.event_id = e.id
LEFT JOIN order_notification_subscription s ON s.id = o.subscription_id
WHERE e.order_number = 'YOUR_ORDER_NUMBER'
ORDER BY e.id, o.id;

SELECT channel, destination, detail_level, active, source
FROM order_notification_subscription
WHERE order_number = 'YOUR_ORDER_NUMBER';
```

Expected for a WhatsApp order: active `whatsapp_restaurant`, destination equal to its customer number, and successful order events `sent` with `attempts=1`. Address-only actions have no outbox row. Inspect the service log for `customer notifier: order=... channel=whatsapp_restaurant outcome=sent attempts=1`.

`sent` means the restaurant webhook returned success; the customer-message comparison proves the downstream customer actually received the expected message. A failed row must remain at one attempt after the sweep/replay. Do not reset its attempts or manually resend it as part of a verification run.

## 8. Prepare web test order A

Use a separate W-id and WEB thread for each independent R2 order. In the prepared Python terminal:

```zsh
python -c 'from utils_common.order_management.customer_keys import new_web_customer_key; print(new_web_customer_key())'
```

Save the result. In the Supabase SQL editor:

```sql
SELECT * FROM create_thread('WEB', NULL);
```

Save the returned `thread_id` beginning `WEB-`. Open the test API docs and find `POST /order-hooks/capture-address` → **Try it out**.

Fill the request with the new W-id as `recipient`, `rest_ref: "BNAT"`, and the approved BNAT test delivery address. Use that address's real postcode and numeric latitude/longitude, not example coordinates. The required fields are `recipient`, `rest_ref`, `city`, `postcode`, `latitude`, and `longitude`; include the house/street details as appropriate.

Execute. Expected: `{"success": true}`. The Ordelo log should say the web address hook was skipped. No restaurant-app address request should appear. No order customer event is expected at this pre-order step.

## 9. Create the web order through the existing endpoint

In the same API docs, use `POST /order-hooks/create-order/{rest_ref}` with path `rest_ref=BNAT`. Fill the request using this template. Replace every angle-bracket value, including the numeric menu price; the template is not executable JSON until you do so.

```text
{
  "recipient": "<NEW_W_ID>",
  "thread_id": "<NEW_WEB_THREAD_ID>",
  "order_items": [{
    "order_id": "",
    "product_name": "<APPROVED_TEST_MENU_ITEM>",
    "sku": "<THAT_ITEM_SKU>",
    "quantity": 1,
    "price": <THAT_ITEM_PRICE_IN_POUNDS>
  }],
  "order_type": "delivery",
  "notes": "R2 verification A; coordinated BNAT test",
  "origin_channel": "web",
  "storefront": "ordelo",
  "test_payment": true
}
```

Obtain the SKU and price from the actual BNAT menu/API response. The item `order_id` is required by the request model but is replaced by the newly generated order ID. Do not put `test` in the generated order number; use the normal returned reference.

Expected response: `status: "success"`, an `order_id`, `order_number`, `payment_intent_url`, and **`payment_mode: "test"`**. Save them. Stop if the mode is `live` or the request fails.

Check the authoritative order row:

```sql
SELECT order_id, order_number, recipient, thread_id,
       origin_channel, storefront, payment_mode, payment_status
FROM food_order
WHERE order_id = 'YOUR_ORDER_ID';
```

Expected: your W-id/WEB thread, `web`, `ordelo`, `test`, and initially `requires_payment`. The active origin subscription should be `web_page` with a null destination. Do not use the fixture storefront as proof of this R2 flow; its live ordering integration belongs to R3.

## 10. Pay in the browser and record the return URL

Open the returned `payment_intent_url` in the browser. Confirm Stripe presents a test-mode checkout. Use card `4242 4242 4242 4242`, a future expiry such as `12/34`, and CVC `123`. These are Stripe's documented interactive test values: [Stripe testing documentation](https://docs.stripe.com/testing?testing-method=card-numbers).

Submit once. Save the Checkout Session ID, event ID `evt_...`, PaymentIntent ID `pi_...`, amount, and time from the Stripe test dashboard. Record the browser's full final URL and visible page.

The inspected payment-service source configures BNAT's success/cancel destination as `https://restaurant.ordelo.app/restaurant/bnat`. Observe the actual destination; local code is not proof of deployed behavior. A return to that menu rather than an Ordelo order-status page is the known R2 redirect gap.

## 11. Prove payment was applied once and the restaurant app was skipped

Allow the webhook/background tasks to finish. Run:

```sql
SELECT provider_event_id, kind, payment_intent_id, amount_pence, received_at
FROM payment_event
WHERE order_id = 'YOUR_ORDER_ID'
ORDER BY id;

SELECT order_number, payment_id
FROM payment_details
WHERE order_number = 'YOUR_ORDER_ID';

SELECT order_number, status
FROM delivery_summary
WHERE order_number = 'YOUR_ORDER_NUMBER';
```

Also repeat the order and notifier queries from steps 7/9. Expected:

- One `authorised` application linked to the real test Stripe event/PaymentIntent; the order moves to `requires_capture`.
- The payment service has stored the PaymentIntent in `payment_details`. Its
  `order_number` column contains the short `order_id` (for example `LXGM-21`),
  not the full Ordelo reference (`ELAS-LXGM-21`).
- One delivery summary exists, and the log records one successful `init_delivery` for this order.
- One `payment_authorised` customer event; its `web_page` outbox row is `skipped`, `attempts=1`.
- Local logs show `web order, restaurant-app payment-complete skipped` and `channel=web_page outcome=skipped`.
- There is no restaurant-app HTTP request containing this order/W-id. Check the restaurant application's access logs as well as Ordelo's logs. An absence of Ordelo errors alone does not prove no request was sent.

For a convenient local log check:

```zsh
rg -n -F 'YOUR_ORDER_NUMBER' /private/tmp/ordelo-r1b-manual-service.log
rg -n -F 'YOUR_ORDER_ID' /private/tmp/ordelo-r1b-manual-service.log
```

If using the previously started session instead, its log was `/private/tmp/ordelo-r1b-service.log`. Check that it belongs to your current run before relying on it.

## 12. Replay the same actual payment event three times

Copy the original `checkout.session.completed` event JSON from Stripe's test dashboard. In API docs, POST that unchanged JSON three times to `/payment-hooks/payment-complete`. Keep the original `id`, `metadata.orderID`, session, and PaymentIntent IDs.

Expected each time: HTTP 200 with `outcome: "duplicate"`. Re-run step 11's queries and log checks:

- Still one `authorised` application, one payment customer event, and one delivery summary.
- No additional `init_delivery`, outbox send, or restaurant-app/customer message.
- Diagnostic `authorised_duplicate` rows may be added. Total `payment_event` row count is therefore not an invariant.

The stored `payment_event.payload` is redacted and is not a full replayable Stripe event. Copy from Stripe instead. Do not use `/payment-complete-test` to simulate a paid checkout; it is normally disabled and would not prove Stripe/payment-service delivery.

## 13. Check capture and cancellation using two different orders

**Order A — capture:** allow the normal BNAT restaurant-confirmation/dispatch flow to proceed, then have the designated test rider accept. Verify the assigned rider/status using the existing delivery workflow and service logs. In Stripe, inspect that same PaymentIntent: it should move from `requires_capture` to `succeeded`. Confirm the payment service's capture response/log and the notifier's `rider_assigned` event, still `web_page`/`skipped`. Capture can invoke the configured printer.

If completing the remaining delivery transitions, use the actual pickup/customer codes and normal workflow. `food_collected`, `rider_near_customer` (when its location trigger occurs), and `delivered` must also stay on the web channel with no restaurant-app customer request. Mark unexercised transitions as not checked manually.

**Order B — cancellation:** repeat steps 8–11 with a fresh W-id, fresh WEB thread, new create-order request, and a separate Stripe test payment. Coordinate the test so no rider accepts this order; keep the normal timeout scheduler running. Wait for the actual no-rider timeout. Verify:

- Delivery reaches its timed-out state through the normal process.
- Stripe's PaymentIntent becomes `canceled`.
- `no_rider_found` exists on the web channel, its outbox is `skipped`, and its payload records the verified cancellation result.
- Neither timeout nor any earlier event calls the restaurant app for that W-id.

Inspect the recorded cancellation result with:

```sql
SELECT event_key, data->'payload'->>'payment_cancelled' AS payment_cancelled
FROM order_customer_event
WHERE order_number = 'YOUR_ORDER_B_NUMBER'
  AND event_type = 'no_rider_found';
```

Expected cancellation flag: true, corroborated by Stripe. Manually canceling in Stripe or manually setting the delivery status would not verify the application's cancel-on-no-rider path.

Do not use `food_order.payment_status` alone as proof of capture/cancellation; current code does not consistently synchronize that column after those operations. Stripe's actual PaymentIntent status is decisive. Do not require new `capture_*`/`cancel_*` audit rows unless the current capture/cancel path writes them.

## 14. Restore settings and write down the result

Finish or resolve the test jobs/authorizations before ending the window. Restore the two service URLs and both notifier settings to their recorded original values. For URL rows, use:

```sql
BEGIN;
UPDATE ordelo_config
SET config_value = 'SAVED_ORIGINAL_ORDELO_URL', updated_at = now()
WHERE config_key = 'ORDELO_APP_URL';
UPDATE ordelo_config
SET config_value = 'SAVED_ORIGINAL_MENU_URL', updated_at = now()
WHERE config_key = 'RESTAURANT_MENU_APP_URL';
COMMIT;
```

Replace the placeholders before running. If **both notifier rows were absent before this run**, restore that exact state with:

```sql
DELETE FROM ordelo_config
WHERE config_key IN ('CUSTOMER_NOTIFIER_ENABLED', 'CUSTOMER_NOTIFIER_REST_REFS');
```

Otherwise restore each previously existing notifier value and delete only the specific key that was originally absent. Restore any Stripe test destination temporarily changed, using its saved original registration. Never alter a live event destination for this test.

Re-read the configuration, clear/wait out the affected running consumers' caches, and verify production routing before stopping local services. Keep an existing shared tunnel running. Retain evidence before cleaning disposable test records; use the recorded order/customer/thread IDs and the project's existing cleanup procedure, not a broad delete.

Record these results in the release notes:

| Result | Evidence to save |
| --- | --- |
| WhatsApp behavior unchanged | Flag-off/on delivery and takeaway message comparisons, order references |
| Actual web authorization applied once | Stripe event/PaymentIntent, `payment_details`, authorization row, one initialization |
| Replay harmless | Three `duplicate` responses, unchanged business event/outbox/initialization |
| No restaurant-app customer request | Web outbox rows plus Ordelo and restaurant-app access logs |
| Capture on acceptance | Order A, rider acceptance, Stripe `succeeded` |
| Cancel on no rider | Order B, normal timeout, Stripe `canceled`, cancellation flag |
| Browser return | Actual URL after payment; distinguish observed behavior from source expectation |
| Webhook configuration | Ordelo endpoint and subscribed events for every Stripe account in scope |
| Restoration | Original/final settings, destination restoration, production-routing check |

R1b/R2 acceptance remains open for any unchecked item. Passing isolated tests or seeing the menu load does not replace these paid-flow results.
