-- Ordelo web checkout: production PAUSE / UNPAUSE profiles.
-- PAUSE values were applied and verified on 2026-10-02 at 15:39 Europe/London.
-- Save the inspection below before making changes. Run ONE profile only.
-- Running the whole file applies PAUSE; UNPAUSE is deliberately commented out.
-- To unpause, select only its SQL from BEGIN through COMMIT inside the comment.
-- Both profiles retain the late-payment guard and BNAT test-payment baseline.
-- They do not change app URLs, existing notifier/payment flags, provider
-- callbacks, frontend environment, in-flight fulfilment or the R3 schema.

-- INSPECT: run and save before either switch; repeat after the selected profile.
SELECT config_key, config_value, description, updated_at
FROM public.ordelo_config
WHERE config_key IN (
  'ORDELO_APP_URL', 'RESTAURANT_MENU_APP_URL',
  'PAYMENT_INBOX_ENABLED', 'ORDER_CREATE_RPC_ENABLED',
  'ENABLE_PAYMENT_TEST_ROUTES', 'CUSTOMER_NOTIFIER_ENABLED',
  'CUSTOMER_NOTIFIER_REST_REFS', 'TEST_PAYMENT_REST_REFS',
  'WEB_ORDERING_ENABLED_REST_REFS', 'WEB_LATE_PAYMENT_GUARD_ENABLED',
  'WEB_PRICE_MONITOR_ENABLED', 'ELAS_WEB_MAX_DISCOUNT_PERCENT'
)
ORDER BY config_key;

-- PAUSE: stop new web checkouts while tracking/financial recovery remain enabled.
BEGIN;
INSERT INTO public.ordelo_config(config_key, config_value, description)
VALUES
  ('TEST_PAYMENT_REST_REFS', 'BNAT', 'Restaurants eligible for requested Stripe test payments'),
  ('WEB_ORDERING_ENABLED_REST_REFS', '', 'Restaurants accepting new web checkout; empty disables checkout'),
  ('WEB_LATE_PAYMENT_GUARD_ENABLED', 'true', 'Keep web late-payment rejection and financial reconciliation enabled')
ON CONFLICT(config_key) DO UPDATE
SET config_value=EXCLUDED.config_value, updated_at=CURRENT_TIMESTAMP;
COMMIT;

-- UNPAUSE: enable ELAS only, after resolving the production-handover launch
-- gates (including manual collection capture) and configuring the live frontend.
-- This profile has not been applied. It does not complete those launch checks.
-- /*
BEGIN;

-- Refuse activation if the existing payment/order/notifier prerequisites are off.
DO $$
BEGIN
  IF (
    SELECT count(*) FROM public.ordelo_config
    WHERE config_key IN (
      'PAYMENT_INBOX_ENABLED', 'ORDER_CREATE_RPC_ENABLED', 'CUSTOMER_NOTIFIER_ENABLED'
    ) AND lower(trim(config_value)) IN ('true', '1', 'yes', 'on')
  ) <> 3 THEN
    RAISE EXCEPTION 'Unpause requires payment inbox, order RPC and customer notifier enabled';
  END IF;
END $$;

INSERT INTO public.ordelo_config(config_key, config_value, description)
VALUES
  ('TEST_PAYMENT_REST_REFS', 'BNAT', 'Restaurants eligible for requested Stripe test payments'),
  ('WEB_ORDERING_ENABLED_REST_REFS', 'ELAS', 'Restaurants accepting new web checkout'),
  ('WEB_LATE_PAYMENT_GUARD_ENABLED', 'true', 'Keep web late-payment rejection and financial reconciliation enabled')
ON CONFLICT(config_key) DO UPDATE
SET config_value=EXCLUDED.config_value, updated_at=CURRENT_TIMESTAMP;

COMMIT;
-- */

-- VERIFY: run after the chosen profile. Flags can take 60 seconds to refresh.
SELECT config_key, config_value, updated_at
FROM public.ordelo_config
WHERE config_key IN (
  'ORDELO_APP_URL', 'RESTAURANT_MENU_APP_URL',
  'PAYMENT_INBOX_ENABLED', 'ORDER_CREATE_RPC_ENABLED',
  'ENABLE_PAYMENT_TEST_ROUTES', 'CUSTOMER_NOTIFIER_ENABLED',
  'CUSTOMER_NOTIFIER_REST_REFS', 'TEST_PAYMENT_REST_REFS',
  'WEB_ORDERING_ENABLED_REST_REFS', 'WEB_LATE_PAYMENT_GUARD_ENABLED'
)
ORDER BY config_key;
