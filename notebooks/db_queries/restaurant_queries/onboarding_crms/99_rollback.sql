-- Payment testing uses an exact TEST3100 item; ordinary new baskets use live.
-- ===
-- CRMS onboarding · 99 · ROLLBACK. Pick the smallest level that solves the problem.
-- All levels take effect within about 60 s (backend flag/CSV cache), with no deploy.
-- =============================================================================

-- ---------- Level 1: pause all new CRMS web orders (normal "turn it off") ----------
BEGIN;
INSERT INTO public.ordelo_config (config_key, config_value, description)
VALUES ('CRMS_WEB_ORDERING_PAUSED', 'true', 'Emergency stop for new CRMS web orders')
ON CONFLICT (config_key) DO UPDATE SET config_value = 'true', updated_at = CURRENT_TIMESTAMP;
SELECT config_key, config_value FROM public.ordelo_config WHERE config_key = 'CRMS_WEB_ORDERING_PAUSED';
COMMIT;

-- ---------- Level 2: delivery only ----------
-- No longer available (R3.1 removed CRMS_WEB_DELIVERY_PAUSED). Use Level 1.

-- ---------- Level 3: take CRMS off the web ----------
-- Since R3.1 there is no allowlist row: remove RESTAURANTS["CRMS"] (backend) and
-- RESTAURANTS.crms webOrderingEnabled (frontend) and deploy. Level 1 meanwhile.

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
