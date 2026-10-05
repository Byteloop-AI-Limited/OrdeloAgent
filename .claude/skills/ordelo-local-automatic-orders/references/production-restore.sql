-- SUPERSEDED BY R3.1 (plan D35, 2026-10-05). The rollout flags below are ignored by
-- R3.1 code and deleted by notebooks/db_queries/ordelo-agg-db-switch.sql section 1.
-- TEST_PAYMENT_REST_REFS now makes EVERY order of a listed restaurant a Stripe test
-- payment: never list a restaurant with real customers. Use ordelo-agg-db-switch.sql.
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
    ('TEST_PAYMENT_REST_REFS', 'BNAT', 'Restaurants whose orders always use Stripe test (R3.1)')
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
