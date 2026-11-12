-- CRDO ordelo_config keys for manual execution. Not executed by the agent.
-- Apply the pause FIRST, before any backend/frontend route is deployed. Web-only: no CRDO_APP_URL.
-- Values copied from STRK's live keys (read 2026-11-12), except CRDO_WEB_MAX_DISCOUNT_PERCENT = 5 so the nightly
-- price audit allows the 5% Ordelo web offer on the storefront (STRK's 0 is NOT copied).

-- 1. Pause (blocks new web orders; missing/false means open).
INSERT INTO public.ordelo_config (config_key, config_value, description)
VALUES ('CRDO_WEB_ORDERING_PAUSED', 'true', 'Crispy Dosa onboarding: block new web orders pending launch verification')
ON CONFLICT (config_key) DO UPDATE
SET config_value = 'true', description = EXCLUDED.description, updated_at = CURRENT_TIMESTAMP
RETURNING config_key, config_value;

-- 2. Timings, discount ceiling and Telegram alert schedule.
INSERT INTO public.ordelo_config (config_key, config_value, description) VALUES
('CRDO_DEFAULT_DELIVERY_PICKUP_TIME', '30', 'Crispy Dosa delivery pickup default'),
('CRDO_DEFAULT_COLLECTION_PICKUP_TIME', '30', 'Crispy Dosa collection pickup default'),
('CRDO_DELIVERY_TIMEOUT_TIME', '5', 'Crispy Dosa rider dispatch timeout'),
('CRDO_RESTAURANT_CONFIRMATION_TIMEOUT_TIME', '3', 'Crispy Dosa admin confirmation timeout'),
('CRDO_WEB_MAX_DISCOUNT_PERCENT', '5', 'Crispy Dosa maximum web discount (matches the 5% Ordelo web offer)'),
('CRDO_TGRAM_ORDER_ALERT_OFFSETS_SECS', '0,15,30,35', 'CRDO override: seconds after a new order at which the Telegram order card is (re)sent.')
RETURNING config_key, config_value;
-- If a key already exists the INSERT fails: inspect it, then update only the agreed fields.
-- No retired keys (global web allowlist, delivery-only pause, test-payment selector).

-- Verify: the CRDO keys next to STRK's.
SELECT config_key, config_value FROM public.ordelo_config
WHERE left(config_key, 5) IN ('CRDO_', 'STRK_') ORDER BY right(config_key, length(config_key) - 5), config_key;
