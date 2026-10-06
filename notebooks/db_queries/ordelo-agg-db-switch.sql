-- Ordelo configuration switches after R3.1 "one switch" (plan D35, 2026-10-05).
--
-- Since R3.1 every restaurant in the code registries is live on WhatsApp and on
-- the web, with all customer notifications. Which restaurants are on the web is
-- decided in code: backend utils_common/web_ordering/common.py RESTAURANTS and
-- frontend config/restaurants.ts webOrderingEnabled. Only two kinds of
-- ordelo_config row remain to manage:
--
--   TEST_PAYMENT_REST_REFS      Comma list. EVERY order (web and WhatsApp) for a
--                               listed restaurant uses Stripe test, requested or
--                               not. Keep it to test restaurants (BNAT). Never
--                               list a restaurant with real customers: they
--                               could pay with Stripe's test card.
--   {REST}_WEB_ORDERING_PAUSED  'true' stops NEW web orders for one restaurant.
--                               Tracking and in-flight orders carry on. Absent
--                               means open; delete the row to reopen.
--
-- Optional, normally absent: {REST}_WEB_MAX_DISCOUNT_PERCENT (daily web price audit;
-- absent = 0%). Set it only when a restaurant has approved web offers.
--
-- App URLs, overwatch_list, timeouts and other restaurant keys are unchanged
-- and are not managed here. Changes take effect within 60 s (backend cache).
--
-- HOW TO RUN: running the whole file only reads. Sections 1-4 are commented out
-- with '-- ': uncomment the SQL of ONE section (BEGIN through COMMIT), run it on
-- its own, re-comment it, then run the two SELECTs at the top again.



SELECT config_key, config_value, updated_at
FROM public.ordelo_config
WHERE config_key IN ('TEST_PAYMENT_REST_REFS', 'ORDELO_APP_URL', 'RESTAURANT_MENU_APP_URL')
   OR config_key LIKE '%\_WEB\_ORDERING\_PAUSED' ESCAPE '\'
   OR config_key LIKE '%\_WEB\_MAX\_DISCOUNT\_PERCENT' ESCAPE '\'
ORDER BY config_key;

-- ---------- 1. ONE-OFF R3.1 CLEAN-UP ---------
--    Run once, only after R3.1 is deployed to production and has settled.
--    Code older than R3.1 treats a missing row as OFF: deleting these first, or
--    rolling back to an older image afterwards, switches the payment inbox,
--    order RPC, notifier and web ordering off. Save the second SELECT above
--    first so the rows can be put back for a rollback.
--    Also sets the test list to BNAT only, so CRMS and ELAS take live payments.

-- BEGIN;

INSERT INTO public.ordelo_config (config_key, config_value, description)
VALUES ('TEST_PAYMENT_REST_REFS', 'BNAT,ELAS,SFCS', 'Restaurants whose orders always use Stripe test (R3.1)')
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value, description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;

update public.ordelo_config
set config_value = 'BNAT,ELAS', updated_at = CURRENT_TIMESTAMP
where config_key = 'TEST_PAYMENT_REST_REFS';
-- COMMIT;


-- ---------- 2. SET THE TEST RESTAURANT LIST ----------
--    Edit the value, comma-separated, e.g. 'BNAT' or 'BNAT,CRMS' while CRMS is in
--    a test window. Removing a restaurant makes its new orders live.

-- BEGIN;

INSERT INTO public.ordelo_config (config_key, config_value, description)
VALUES ('TEST_PAYMENT_REST_REFS', 'BNAT', 'Restaurants whose orders always use Stripe test (R3.1)')
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value, updated_at = CURRENT_TIMESTAMP;

-- COMMIT;


-- ---------- 3. EMERGENCY: PAUSE NEW WEB ORDERS FOR ONE RESTAURANT ----------
--    Replace ELAS with the restaurant. The web page answers "ordering paused";
--    WhatsApp ordering and in-flight orders are not affected.

-- BEGIN;

INSERT INTO public.ordelo_config (config_key, config_value, description)
VALUES ('ELAS_WEB_ORDERING_PAUSED', 'false', 'Emergency stop for new web orders (R3.1)')
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value, updated_at = CURRENT_TIMESTAMP;

-- COMMIT;


-- ---------- 4. REOPEN WEB ORDERS FOR ONE RESTAURANT ----------
--    Replace ELAS with the restaurant.

-- BEGIN;

-- DELETE FROM public.ordelo_config WHERE config_key = 'ELAS_WEB_ORDERING_PAUSED';

-- COMMIT;


-- Old rollout rows. R3.1 code ignores them; section 1 deletes them.
-- Expect no rows once section 1 has run.
SELECT config_key, config_value, updated_at
FROM public.ordelo_config
WHERE config_key IN (
    'PAYMENT_INBOX_ENABLED', 'ORDER_CREATE_RPC_ENABLED', 'ENABLE_PAYMENT_TEST_ROUTES',
    'CUSTOMER_NOTIFIER_ENABLED', 'CUSTOMER_NOTIFIER_REST_REFS',
    'WEB_ORDERING_ENABLED_REST_REFS', 'WEB_LATE_PAYMENT_GUARD_ENABLED',
    'WEB_PRICE_MONITOR_ENABLED'
)
   OR config_key LIKE '%\_WEB\_DELIVERY\_PAUSED' ESCAPE '\'
ORDER BY config_key;


