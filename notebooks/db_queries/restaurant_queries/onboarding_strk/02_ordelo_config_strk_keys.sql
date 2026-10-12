-- Proposed STRK identity. Setup pause only; review before manual execution.
-- Apply before enabling a backend/frontend route. Confirm via actual checkout.
INSERT INTO public.ordelo_config (config_key,config_value,description)
VALUES ('STRK_WEB_ORDERING_PAUSED','true','Strikers onboarding: block new web orders pending launch verification')
ON CONFLICT (config_key) DO UPDATE
SET config_value='true',description=EXCLUDED.description,updated_at=CURRENT_TIMESTAMP
RETURNING config_key,config_value;

-- Incomplete timing/offer draft: replace with agreed values before enabling.
INSERT INTO public.ordelo_config (config_key,config_value,description) VALUES
('STRK_DEFAULT_DELIVERY_PICKUP_TIME','30','Strikers delivery pickup default'),
('STRK_DEFAULT_COLLECTION_PICKUP_TIME','30','Strikers collection pickup default'),
('STRK_DELIVERY_TIMEOUT_TIME','5','Strikers rider dispatch timeout'),
('STRK_RESTAURANT_CONFIRMATION_TIMEOUT_TIME','3','Strikers admin confirmation timeout'),
('STRK_WEB_MAX_DISCOUNT_PERCENT','0','Strikers maximum web discount')
RETURNING config_key,config_value;
-- For an existing key, inspect then update only the agreed fields.
-- Web-only: no STRK_APP_URL. Channel decision remains pending.
-- No retired global web allowlist, delivery-only pause or test-payment selector.
SELECT config_key,config_value FROM public.ordelo_config
WHERE left(config_key,5)='STRK_' ORDER BY config_key;


SELECT config_key,config_value FROM public.ordelo_config
WHERE left(config_key,5)='CRMS_' ORDER BY config_key;


