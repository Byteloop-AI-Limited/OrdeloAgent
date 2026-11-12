-- CRDO go live. NOT to be run until every gate in plans/onboard-crdo-plan.md has passed and the owner approves.
-- Gates: test orders (TEST3100) passed for the requested modes; payment/payout mapping confirmed in the deployed
-- payment service; delivery quotes and rider coverage confirmed; admins receive actionable alerts; menu and
-- discount audit clean. Each statement runs on its own; mutations stay commented until then.

-- 1. Prerequisites: admins, timeout, pause state, menu row count (146).
SELECT rest_ref, admins, auto_accept, collection_commission FROM public.restaurant_master WHERE rest_ref = 'CRDO';
SELECT config_key, config_value FROM public.ordelo_config WHERE left(config_key, 5) = 'CRDO_' ORDER BY config_key;
SELECT count(*) AS menu_items FROM public.crdo_menu;

-- 2. Admins and confirmation timeout were copied from STRK. Change them only if the restaurant gives its own
--    numbers or timeout; after changing admins reset the cache: POST {ordelo}/internal/cache/reset?rest_ref=CRDO
--    (RestaurantMaster caches for an hour; use the current authenticated contract).
-- UPDATE public.restaurant_master SET admins = ARRAY['<NUMBER_1>','<NUMBER_2>'] WHERE rest_ref = 'CRDO' RETURNING rest_ref, admins;
-- UPDATE public.ordelo_config SET config_value = '<MINUTES>', updated_at = CURRENT_TIMESTAMP
-- WHERE config_key = 'CRDO_RESTAURANT_CONFIRMATION_TIMEOUT_TIME' RETURNING config_key, config_value;

-- 3. Final step, separate statement: remove the pause (sets false; the key is not deleted).
-- UPDATE public.ordelo_config SET config_value = 'false', updated_at = CURRENT_TIMESTAMP
-- WHERE config_key = 'CRDO_WEB_ORDERING_PAUSED'
-- RETURNING config_key, config_value;
