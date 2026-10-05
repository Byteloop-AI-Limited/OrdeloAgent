-- =============================================================================
-- CRMS onboarding · 02 · per-restaurant ordelo_config keys (CRMS_*)
-- Idempotent. Web checkout stays PAUSED for CRMS after this file
-- (CRMS_WEB_ORDERING_PAUSED = true).
-- CRMS_APP_URL is deliberately NOT created. CRMS has no restaurant-agents app,
-- and ADR-0003 says web orders never call one. job_terminate_stale_active_threads
-- skips restaurants with no base URL.
-- =============================================================================
BEGIN;

INSERT INTO public.ordelo_config (config_key, config_value, description)
VALUES
  ('CRMS_DEFAULT_DELIVERY_PICKUP_TIME',         '17',
   'CRMS delivery pickup default (minutes) for auto/timeout acceptance. Copied from BNAT'),
  ('CRMS_DEFAULT_COLLECTION_PICKUP_TIME',       '17',
   'CRMS collection pickup default (minutes) for auto/timeout acceptance. Copied from BNAT'),
  ('CRMS_DELIVERY_TIMEOUT_TIME',                '5',
   'Minutes before a CRMS delivery_summary dispatch transitions to timedout. Copied from BNAT'),
  ('CRMS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME', '3',
   'Minutes before an unanswered CRMS admin confirmation times out. 3 for the test phase; review at go-live (04)'),
  ('CRMS_WEB_MAX_DISCOUNT_PERCENT',             '0',
   'Nightly web price audit floor for CRMS: no discount at launch (no ordeloOffers in the frontend)'),
  ('CRMS_WEB_ORDERING_PAUSED',                  'true',
   'Kill switch: true blocks new CRMS web orders (both modes). Flipped by 03/04')
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value,
    description  = EXCLUDED.description,
    updated_at   = CURRENT_TIMESTAMP;

-- Verify before COMMIT: expect 6 rows.
SELECT config_key, config_value FROM public.ordelo_config
WHERE config_key LIKE 'CRMS\_%' ORDER BY config_key;

COMMIT;   -- change to ROLLBACK for a dry run
