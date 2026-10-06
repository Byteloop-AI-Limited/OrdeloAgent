-- SUPERSEDED BY R3.1 (plan D35, 2026-10-05). The rollout flags below are ignored by
-- R3.1 code and deleted by notebooks/db_queries/ordelo-agg-db-switch.sql section 1.
-- TEST_PAYMENT_REST_REFS now makes EVERY order of a listed restaurant a Stripe test
-- payment: never list a restaurant with real customers. Use ordelo-agg-db-switch.sql.
-- Re-enable the successful ELAS/BNAT local R1b/R2 profile from 2026-10-02.
-- Maintenance window: all shared DB consumers see these test URLs.
-- First start/reach the local 3100/3000 services and existing tunnel.
-- Local code and existing R1a/R1b tables/RPCs must support these flags.
-- Run the initial SELECT separately and export it before applying the file.
-- Normally restore that exact snapshot; then run the whole file to enable testing.
-- This does not reroute restaurant-agent backends or change timeouts/riders.
-- Stripe test + Meta ingress are separate: see configuration.md.
-- ENABLE_PAYMENT_TEST_ROUTES stays false: normal Stripe events need no test route.

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
    ('ORDELO_APP_URL', 'https://rider-agent-test.ordelo.app', 'URL for Ordelo app'),
    ('RESTAURANT_MENU_APP_URL', 'https://restaurant-test.ordelo.app', 'URL for restaurant frontend'),
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
    'CUSTOMER_NOTIFIER_REST_REFS', 'TEST_PAYMENT_REST_REFS'
)
ORDER BY config_key;
