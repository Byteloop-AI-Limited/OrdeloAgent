-- CRDO (Crispy Dosa Orpington) onboarding · 00 · READ-ONLY preflight. Not executed by the agent.
-- Run each statement on its own. Expected results are in the comments.

-- Collisions: expect 0 rows for both.
SELECT rest_ref, rest_id, rest_name FROM public.restaurant_master
WHERE rest_ref = 'CRDO' OR rest_id = 'CRDO01';

-- Actual restaurant_master schema/nullability (rest_email is omitted from 01: it must be nullable).
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'restaurant_master'
ORDER BY ordinal_position;

-- Existing config: expect 0 rows.
SELECT config_key, config_value FROM public.ordelo_config
WHERE left(config_key, 5) = 'CRDO_' ORDER BY config_key;

-- Menu table: expect NULL before core/menus.sql, 'crdo_menu' after.
SELECT to_regclass('public.crdo_menu') AS existing_menu;

-- Order and session history under this ref: expect 0 and 0.
SELECT count(*) AS existing_orders FROM public.food_order WHERE order_number LIKE 'CRDO-%';
SELECT count(*) AS existing_sessions FROM public.web_session_meta WHERE rest_ref = 'CRDO';

-- Reference rows to copy from (STRK): admins, timings, commission, config keys.
SELECT rest_ref, rest_id, admins, auto_accept, collection_commission,
       delivery_order_cutoff_minutes, takeaway_order_cutoff_minutes,
       rest_stale_active_threads_minutes
FROM public.restaurant_master WHERE rest_ref = 'STRK';
SELECT config_key, config_value FROM public.ordelo_config
WHERE left(config_key, 5) = 'STRK_' ORDER BY config_key;
