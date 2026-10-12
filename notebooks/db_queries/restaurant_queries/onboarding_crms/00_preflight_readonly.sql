-- =============================================================================
-- CRMS onboarding · 00 · PRE-FLIGHT (read-only). Safe to run any time.
-- Plan: plans/onboard-crms-plan.md · Runbook: docs/onboarding-web-only-restaurant.md
-- Run this before 01. Every check should return the "expected" result.
-- =============================================================================

-- 1. CRMS must not exist yet (expected: 0 rows). BNAT is shown for comparison.
SELECT rest_ref, rest_id, rest_name, city, postcode, auto_accept,
       service_hours_json, delivery_order_cutoff_minutes, takeaway_order_cutoff_minutes,
       collection_commission
FROM public.restaurant_master
WHERE rest_ref IN ('CRMS', 'BNAT');

-- 2. rest_id is UNIQUE. Expected: 0 rows (nobody already uses 447595246457).
SELECT rest_ref, rest_id FROM public.restaurant_master WHERE rest_id = '447595246457';

-- 3. Columns the web path reads must exist. Expected: 7 rows.
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'restaurant_master'
  AND column_name IN ('service_hours_json', 'collection_commission', 'auto_accept',
                      'delivery_order_cutoff_minutes', 'takeaway_order_cutoff_minutes',
                      'rest_stale_active_threads_minutes', 'restaurant_end_time')
ORDER BY column_name;

-- 4. CRMS config keys: expected 0 rows. BNAT keys are shown for comparison.
SELECT config_key, config_value
FROM public.ordelo_config
WHERE config_key LIKE 'CRMS\_%' OR config_key LIKE 'BNAT\_%'
ORDER BY config_key;

-- 5. Global web switches. Note the current values; 03/04 append to them and never overwrite.
SELECT config_key, config_value
FROM public.ordelo_config
WHERE config_key IN ('WEB_ORDERING_ENABLED_REST_REFS', 'PAYMENT_INBOX_ENABLED', 'ORDER_CREATE_RPC_ENABLED',
                     'WEB_LATE_PAYMENT_GUARD_ENABLED', 'WEB_PRICE_MONITOR_ENABLED',
                     'DEFAULT_DELIVERY_PICKUP_TIME', 'DEFAULT_COLLECTION_PICKUP_TIME')
ORDER BY config_key;

-- 6. Menu sanity. crms_menu feeds the menu service (apiName 'crms') and the
--    nightly web price audit, which joins order lines to crms_menu by title.
SELECT count(*) AS items,
       count(*) FILTER (WHERE price IS NULL OR price <= 0) AS bad_price,
       count(*) FILTER (WHERE title IS NULL OR btrim(title) = '') AS no_title,
       count(DISTINCT category) AS categories
FROM public.crms_menu;   -- expected: items > 0, bad_price = 0, no_title = 0

-- 7. Duplicate titles. The price audit takes min(price) for duplicates, so a cheap
--    duplicate hides an under-priced line. Review any rows returned.
SELECT lower(btrim(title)) AS title_key, count(*), min(price), max(price)
FROM public.crms_menu
GROUP BY 1 HAVING count(*) > 1
ORDER BY 2 DESC;
