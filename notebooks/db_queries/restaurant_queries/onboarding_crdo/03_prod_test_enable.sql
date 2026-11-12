-- CRDO test window. NOT to be run until the launch gates in plans/onboard-crdo-plan.md pass:
-- menu-manager, backend and frontend deployed, payment mapping confirmed, paused checkout verified.
-- Every test basket must contain the exact normal priced item TEST3100 (accepted item selects test payment).
-- An ordinary basket uses live payment even during this window. Run each statement on its own.

-- Open the window (sets false instead of deleting the key; absent or false both mean open).
-- UPDATE public.ordelo_config SET config_value = 'false', updated_at = CURRENT_TIMESTAMP
-- WHERE config_key = 'CRDO_WEB_ORDERING_PAUSED'
-- RETURNING config_key, config_value;

-- Verify the pause state and recent orders / payment mode.
SELECT config_key, config_value FROM public.ordelo_config WHERE config_key = 'CRDO_WEB_ORDERING_PAUSED';

SELECT fo.order_number, fo.origin_channel, fo.payment_mode, fo.order_dtts,
       EXISTS (SELECT 1 FROM public.order_item oi
               WHERE oi.order_id = fo.order_id AND oi.product_name = 'TEST3100') AS has_test_item
FROM public.food_order fo WHERE fo.order_number LIKE 'CRDO-%'
ORDER BY fo.order_dtts DESC LIMIT 20;

-- Re-pause after the test window (separate statement).
-- UPDATE public.ordelo_config SET config_value = 'true', updated_at = CURRENT_TIMESTAMP
-- WHERE config_key = 'CRDO_WEB_ORDERING_PAUSED'
-- RETURNING config_key, config_value;
