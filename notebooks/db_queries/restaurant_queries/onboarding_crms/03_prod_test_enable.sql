-- =============================================================================
-- CRMS onboarding · 03 · PRODUCTION TEST WINDOW (open), then RE-PAUSE
-- Only run this AFTER both deployments are live:
--   OrdeloAgent: RESTAURANTS["CRMS"] in utils_common/web_ordering/common.py
--   frontend:    RESTAURANTS.crms + TOWNS.orpington
-- Accepted risk (agreed): while CRMS is unpaused, a visitor who does NOT add
-- ?isTest3100=true pays LIVE. Keep the window short.
-- Backend flag/CSV caches last 60 s, so wait about a minute after COMMIT.
-- =============================================================================

-- ---------- 3A. OPEN the test window ----------
BEGIN;

-- Append CRMS to the global allowlist without overwriting other restaurants.
INSERT INTO public.ordelo_config (config_key, config_value, description)
VALUES ('WEB_ORDERING_ENABLED_REST_REFS', 'CRMS', 'Restaurants accepting new web checkout; empty disables checkout')
ON CONFLICT (config_key) DO UPDATE
SET config_value = CASE
      WHEN 'CRMS' = ANY (string_to_array(upper(replace(ordelo_config.config_value, ' ', '')), ',')) THEN ordelo_config.config_value
      WHEN btrim(ordelo_config.config_value) = '' THEN 'CRMS'
      ELSE ordelo_config.config_value || ',CRMS'
    END,
    updated_at = CURRENT_TIMESTAMP;

-- Allow ?isTest3100=true (Stripe test mode) for CRMS web orders.
INSERT INTO public.ordelo_config (config_key, config_value, description)
VALUES ('TEST_PAYMENT_REST_REFS', 'CRMS', 'Restaurants eligible for requested Stripe test payments')
ON CONFLICT (config_key) DO UPDATE
SET config_value = CASE
      WHEN 'CRMS' = ANY (string_to_array(upper(replace(ordelo_config.config_value, ' ', '')), ',')) THEN ordelo_config.config_value
      WHEN btrim(ordelo_config.config_value) = '' THEN 'CRMS'
      ELSE ordelo_config.config_value || ',CRMS'
    END,
    updated_at = CURRENT_TIMESTAMP;

UPDATE public.ordelo_config SET config_value = 'false', updated_at = CURRENT_TIMESTAMP
WHERE config_key = 'CRMS_WEB_ORDERING_PAUSED';

-- Verify: CRMS appears in both lists; PAUSED = false.
SELECT config_key, config_value FROM public.ordelo_config
WHERE config_key IN ('WEB_ORDERING_ENABLED_REST_REFS', 'TEST_PAYMENT_REST_REFS',
                     'CRMS_WEB_ORDERING_PAUSED', 'CRMS_WEB_DELIVERY_PAUSED')
ORDER BY config_key;

COMMIT;

-- ---------- 3B. Inspect test orders (read-only, run as you go) ----------
SELECT order_number, origin_channel, payment_mode, order_dtts
FROM public.food_order
WHERE order_number LIKE 'CRMS-%'
ORDER BY order_dtts DESC
LIMIT 20;
-- Expected for every test order: origin_channel = 'web', payment_mode = 'test'.
-- If payment_mode = 'live' appears, the order was placed WITHOUT ?isTest3100=true:
-- cancel/refund it in Stripe live mode and re-pause immediately (3C).

-- ---------- 3C. RE-PAUSE after testing (CRMS stays in the allowlist) ----------
-- BEGIN;
-- UPDATE public.ordelo_config SET config_value = 'true', updated_at = CURRENT_TIMESTAMP
-- WHERE config_key = 'CRMS_WEB_ORDERING_PAUSED';
-- SELECT config_key, config_value FROM public.ordelo_config WHERE config_key = 'CRMS_WEB_ORDERING_PAUSED';
-- COMMIT;
