-- Production routing / pre-R1b-rollout profile, prepared 2026-10-02.
-- Run the initial SELECT separately and export it before applying the file.
-- Then run the whole file on the authorized shared Ordelo database.
-- R1a stays enabled. This turns OFF the local R1b pilot pending deployment.
-- BNAT-only test-payment eligibility is the existing production plan baseline.
-- A later approved R1b rollout can set notifier=true with BNAT as its pilot.
-- Does not change Meta, Stripe, frontend env, restaurant/rider rows, cron,
-- timeouts, PAYMENT_INIT_RECONCILER_SINCE, or WREN's pre-existing test URL.
-- SQL cannot restore external webhooks. Follow configuration.md as well.

SELECT config_key, config_value, description, updated_at
FROM public.ordelo_config
WHERE config_key IN (
    'ORDELO_APP_URL', 'RESTAURANT_MENU_APP_URL',
    'PAYMENT_INBOX_ENABLED', 'ORDER_CREATE_RPC_ENABLED',
    'ENABLE_PAYMENT_TEST_ROUTES', 'CUSTOMER_NOTIFIER_ENABLED',
    'CUSTOMER_NOTIFIER_REST_REFS', 'TEST_PAYMENT_REST_REFS'
)
ORDER BY config_key;

BEGIN;

INSERT INTO public.ordelo_config (config_key, config_value, description)
VALUES
    ('ORDELO_APP_URL', 'https://rider-agent.ordelo.app', 'URL for Ordelo app'),
    ('RESTAURANT_MENU_APP_URL', 'https://restaurant.ordelo.app', 'URL for restaurant frontend'),
    ('PAYMENT_INBOX_ENABLED', 'true', 'R1a: apply each authorized payment once'),
    ('ORDER_CREATE_RPC_ENABLED', 'true', 'R1a: create order and items atomically'),
    ('ENABLE_PAYMENT_TEST_ROUTES', 'false', 'Keep synthetic payment test route disabled'),
    ('CUSTOMER_NOTIFIER_ENABLED', 'false', 'R1b customer notifier rollout flag'),
    ('CUSTOMER_NOTIFIER_REST_REFS', 'BNAT', 'Restaurants in the notifier pilot'),
    ('TEST_PAYMENT_REST_REFS', 'BNAT', 'Restaurants eligible for requested Stripe test payments')
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value, updated_at = CURRENT_TIMESTAMP;

COMMIT;

SELECT config_key, config_value, updated_at
FROM public.ordelo_config
WHERE config_key IN (
    'ORDELO_APP_URL', 'RESTAURANT_MENU_APP_URL',
    'PAYMENT_INBOX_ENABLED', 'ORDER_CREATE_RPC_ENABLED',
    'ENABLE_PAYMENT_TEST_ROUTES', 'CUSTOMER_NOTIFIER_ENABLED',
    'CUSTOMER_NOTIFIER_REST_REFS', 'TEST_PAYMENT_REST_REFS',
    'BNAT_APP_URL', 'ELAS_APP_URL', 'SFCS_APP_URL', 'WREN_APP_URL'
)
ORDER BY config_key;

-- BNAT_APP_URL was already https://bnat-agent.fly.dev/
-- ELAS_APP_URL was already https://elas-agg.ordelo.app
-- SFCS_APP_URL was already https://sfcs-agent.fly.dev
-- WREN_APP_URL was https://wren-agg-test.ordelo.app since before this test.
-- These are read back, not rewritten. See configuration.md for the scope.
