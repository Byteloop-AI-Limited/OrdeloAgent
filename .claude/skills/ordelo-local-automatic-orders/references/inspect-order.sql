-- Read-only order inspection. Change only the order number below.
-- Execute the whole file so the transaction-local setting spans the SELECTs.
BEGIN READ ONLY;
SELECT set_config('ordelo.testing_order_number', 'ELAS-DQFH-22', true);

SELECT order_number, order_id, recipient, thread_id, origin_channel, storefront,
       payment_mode, payment_status
FROM public.food_order
WHERE order_number = current_setting('ordelo.testing_order_number');

SELECT order_number, status, dtts, redispatch_dtts, restaurant_confirmation_status,
       pickup_time
FROM public.delivery_summary
WHERE order_number = current_setting('ordelo.testing_order_number');

SELECT order_number, vehicle_type, status
FROM public.delivery_detail
WHERE order_number = current_setting('ordelo.testing_order_number');

SELECT dispatch_id, order_number, status, status_update_dtts
FROM public.delivery_dispatch
WHERE order_number = current_setting('ordelo.testing_order_number')
ORDER BY dispatch_id;

SELECT id, kind, provider_event_id, payment_intent_id, amount_pence, received_at
FROM public.payment_event
WHERE order_id IN (
    SELECT order_id FROM public.food_order
    WHERE order_number = current_setting('ordelo.testing_order_number')
)
ORDER BY id;

-- payment_details is public; its order_number stores the SHORT order_id.
SELECT order_number, payment_id
FROM public.payment_details
WHERE order_number IN (
    SELECT order_id FROM public.food_order
    WHERE order_number = current_setting('ordelo.testing_order_number')
);

SELECT id, order_number, event_type, event_key, occurred_at, is_estimate,
       data #>> '{payload,payment_cancelled}' AS payment_cancelled
FROM public.order_customer_event
WHERE order_number = current_setting('ordelo.testing_order_number')
ORDER BY id;

SELECT id, order_number, channel, destination, active, detail_level, source
FROM public.order_notification_subscription
WHERE order_number = current_setting('ordelo.testing_order_number')
ORDER BY id;

SELECT o.id, o.event_id, o.subscription_id, o.status, o.attempts,
       o.last_error, o.next_attempt_at, o.updated_at
FROM public.notification_outbox o
JOIN public.order_customer_event e ON e.id = o.event_id
WHERE e.order_number = current_setting('ordelo.testing_order_number')
ORDER BY o.id;

COMMIT;
