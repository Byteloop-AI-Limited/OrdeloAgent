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
    ('PAYMENT_INBOX_ENABLED', 'true', 'R1a: apply each authorized payment once'),
    ('ORDER_CREATE_RPC_ENABLED', 'true', 'R1a: create order and items atomically'),
    ('ENABLE_PAYMENT_TEST_ROUTES', 'false', 'Keep synthetic payment test route disabled'),
    ('CUSTOMER_NOTIFIER_ENABLED', 'true', 'R1b customer notifier rollout flag'),
    ('CUSTOMER_NOTIFIER_REST_REFS', 'ELAS,BNAT', 'Restaurants in the notifier pilot'),
    ('TEST_PAYMENT_REST_REFS', 'BNAT,ELAS', 'Restaurants eligible for requested Stripe test payments')
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
