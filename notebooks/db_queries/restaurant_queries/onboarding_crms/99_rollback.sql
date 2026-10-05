-- =============================================================================
-- CRMS onboarding · 99 · ROLLBACK. Pick the smallest level that solves the problem.
-- All levels take effect within about 60 s (backend flag/CSV cache), with no deploy.
-- =============================================================================

-- ---------- Level 1: pause all new CRMS web orders (normal "turn it off") ----------
BEGIN;
UPDATE public.ordelo_config SET config_value = 'true', updated_at = CURRENT_TIMESTAMP
WHERE config_key = 'CRMS_WEB_ORDERING_PAUSED';
SELECT config_key, config_value FROM public.ordelo_config WHERE config_key = 'CRMS_WEB_ORDERING_PAUSED';
COMMIT;

-- ---------- Level 2: pause delivery only (e.g. no Orpington riders tonight) ----------
-- BEGIN;
-- UPDATE public.ordelo_config SET config_value = 'true', updated_at = CURRENT_TIMESTAMP
-- WHERE config_key = 'CRMS_WEB_DELIVERY_PAUSED';
-- COMMIT;

-- ---------- Level 3: take CRMS out of the global web lists ----------
-- BEGIN;
-- UPDATE public.ordelo_config
-- SET config_value = array_to_string(
--       array_remove(string_to_array(upper(replace(config_value, ' ', '')), ','), 'CRMS'), ','),
--     updated_at = CURRENT_TIMESTAMP
-- WHERE config_key IN ('WEB_ORDERING_ENABLED_REST_REFS', 'TEST_PAYMENT_REST_REFS');
-- SELECT config_key, config_value FROM public.ordelo_config
-- WHERE config_key IN ('WEB_ORDERING_ENABLED_REST_REFS', 'TEST_PAYMENT_REST_REFS');
-- COMMIT;

-- ---------- Level 4: full removal (only if CRMS never took an order) ----------
-- Check first. Expected: 0 for all three, or do NOT delete (FKs and history).
-- SELECT
--   (SELECT count(*) FROM public.food_order WHERE order_number LIKE 'CRMS-%') AS orders,
--   (SELECT count(*) FROM public.cust_rest_map WHERE rest_ref = 'CRMS')       AS cust_maps,
--   (SELECT count(*) FROM public.web_session_meta WHERE rest_ref = 'CRMS')    AS web_sessions;
-- BEGIN;
-- DELETE FROM public.ordelo_config WHERE config_key LIKE 'CRMS\_%';
-- DELETE FROM public.restaurant_master WHERE rest_ref = 'CRMS';
-- COMMIT;
-- Then revert the code (RESTAURANTS["CRMS"] and RESTAURANTS.crms) or the page
-- returns 404s / 'unknown_restaurant' instead of 'paused'.
