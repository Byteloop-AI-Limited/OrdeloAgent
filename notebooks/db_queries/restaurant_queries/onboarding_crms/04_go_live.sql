-- Updated for R3.1 (plan D35, 2026-10-05): there is no web allowlist or delivery-only
-- pause any more. A restaurant is on the web when it is in the code registries;
-- {REF}_WEB_ORDERING_PAUSED is the only web switch; every order of a restaurant in
-- TEST_PAYMENT_REST_REFS is a Stripe test payment. See ordelo-agg-db-switch.sql.
-- =============================================================================
-- CRMS onboarding · 04 · GO LIVE
-- Pre-conditions (see plan §4.4 gate G3):
--   * every test in plan §4.3 passed
--   * real Creams admin numbers known, and each has messaged the Ordelo WhatsApp
--     number (so they are inside the 24 h window for Accept/Decline messages)
--   * the confirmation timeout value for live is agreed
-- After COMMIT: POST {ordelo}/internal/cache/reset?rest_ref=CRMS so the 1 h
-- RestaurantMaster cache picks up the new admins straight away.
-- =============================================================================
BEGIN;

-- 4.1 Replace the TEMPORARY admin with the Creams staff numbers.
UPDATE public.restaurant_master
SET admins = ARRAY['<TODO_CREAMS_ADMIN_1>', '<TODO_CREAMS_ADMIN_2>']   -- E.164 without +, e.g. 4475...
WHERE rest_ref = 'CRMS';

-- 4.2 Live confirmation timeout (minutes). Test phase used 3. BNAT runs 0.5.
UPDATE public.ordelo_config
SET config_value = '<TODO_LIVE_TIMEOUT_MINUTES>', updated_at = CURRENT_TIMESTAMP
WHERE config_key = 'CRMS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME';

-- 4.3 Take CRMS out of the test list: its orders become live payments.
UPDATE public.ordelo_config
SET config_value = array_to_string(
      array_remove(string_to_array(upper(replace(config_value, ' ', '')), ','), 'CRMS'), ','),
    updated_at = CURRENT_TIMESTAMP
WHERE config_key = 'TEST_PAYMENT_REST_REFS';

-- 4.4 Open for business: remove the pause (absent = open since R3.1).
DELETE FROM public.ordelo_config WHERE config_key = 'CRMS_WEB_ORDERING_PAUSED';

-- Verify before COMMIT. The script fails loudly if a TODO placeholder is still present.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM public.restaurant_master
             WHERE rest_ref = 'CRMS' AND array_to_string(admins, ',') LIKE '%TODO%')
     OR EXISTS (SELECT 1 FROM public.ordelo_config
                WHERE config_key = 'CRMS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME' AND config_value LIKE '%TODO%') THEN
    RAISE EXCEPTION 'Fill the <TODO_...> placeholders before running 04_go_live.sql';
  END IF;
END $$;

SELECT rest_ref, admins FROM public.restaurant_master WHERE rest_ref = 'CRMS';
SELECT config_key, config_value FROM public.ordelo_config
WHERE config_key = 'TEST_PAYMENT_REST_REFS'
   OR config_key LIKE 'CRMS\_%'
ORDER BY config_key;

COMMIT;   -- change to ROLLBACK for a dry run
