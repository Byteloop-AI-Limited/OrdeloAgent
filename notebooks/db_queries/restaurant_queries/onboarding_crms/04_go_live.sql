-- Payment testing uses an exact TEST3100 item; ordinary new baskets use live.
-- ===
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

-- 4.3 Ordinary baskets already use live; no payment switch is changed.

-- Restaurant-wide test selection retired; use a TEST3100 order item.


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
WHERE config_key LIKE 'CRMS\_%'
ORDER BY config_key;

COMMIT;   -- change to ROLLBACK for a dry run
