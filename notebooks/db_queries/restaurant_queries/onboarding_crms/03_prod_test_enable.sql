-- Updated for R3.1 (plan D35, 2026-10-05): there is no web allowlist or delivery-only
-- pause any more. A restaurant is on the web when it is in the code registries;
-- {REF}_WEB_ORDERING_PAUSED is the only web switch; every order of a restaurant in
-- TEST_PAYMENT_REST_REFS is a Stripe test payment. See ordelo-agg-db-switch.sql.
-- =============================================================================
-- CRMS onboarding · 03 · PRODUCTION TEST WINDOW (open), then RE-PAUSE
-- Only run this AFTER both deployments are live:
--   OrdeloAgent: RESTAURANTS["CRMS"] in utils_common/web_ordering/common.py
--   frontend:    RESTAURANTS.crms + TOWNS.orpington
-- While CRMS is in TEST_PAYMENT_REST_REFS every CRMS order is a Stripe test
-- payment (R3.1), with or without ?isTest3100=true.
-- Backend flag/CSV caches last 60 s, so wait about a minute after COMMIT.
-- =============================================================================

-- ---------- 3A. OPEN the test window ----------
BEGIN;

-- Make every CRMS order a Stripe test payment (appends; never overwrites).
INSERT INTO public.ordelo_config (config_key, config_value, description)
VALUES ('TEST_PAYMENT_REST_REFS', 'CRMS', 'Restaurants whose orders always use Stripe test (R3.1)')
ON CONFLICT (config_key) DO UPDATE
SET config_value = CASE
      WHEN 'CRMS' = ANY (string_to_array(upper(replace(ordelo_config.config_value, ' ', '')), ',')) THEN ordelo_config.config_value
      WHEN btrim(ordelo_config.config_value) = '' THEN 'CRMS'
      ELSE ordelo_config.config_value || ',CRMS'
    END,
    updated_at = CURRENT_TIMESTAMP;

-- Unpause (absent = open since R3.1).
DELETE FROM public.ordelo_config WHERE config_key = 'CRMS_WEB_ORDERING_PAUSED';

-- Verify: CRMS is in the test list; no PAUSED row.
SELECT config_key, config_value FROM public.ordelo_config
WHERE config_key IN ('TEST_PAYMENT_REST_REFS', 'CRMS_WEB_ORDERING_PAUSED')
ORDER BY config_key;

COMMIT;

-- ---------- 3B. Inspect test orders (read-only, run as you go) ----------
SELECT order_number, origin_channel, payment_mode, order_dtts
FROM public.food_order
WHERE order_number LIKE 'CRMS-%'
ORDER BY order_dtts DESC
LIMIT 20;
-- Expected for every test order: origin_channel = 'web', payment_mode = 'test'.
-- If payment_mode = 'live' appears, CRMS was not in TEST_PAYMENT_REST_REFS at the
-- time: cancel/refund it in Stripe live mode and re-pause immediately (3C).

-- ---------- 3C. RE-PAUSE after testing ----------
-- BEGIN;
-- INSERT INTO public.ordelo_config (config_key, config_value, description)
-- VALUES ('CRMS_WEB_ORDERING_PAUSED', 'true', 'Emergency stop for new CRMS web orders')
-- ON CONFLICT (config_key) DO UPDATE SET config_value = 'true', updated_at = CURRENT_TIMESTAMP;
-- SELECT config_key, config_value FROM public.ordelo_config WHERE config_key = 'CRMS_WEB_ORDERING_PAUSED';
-- COMMIT;
