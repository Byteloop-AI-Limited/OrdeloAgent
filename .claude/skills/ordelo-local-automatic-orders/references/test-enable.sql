-- Endpoint routing only; payment testing is selected by a TEST3100 item.
-- Export the current URLs before changing them; restore the exact saved values.
-- These defaults do not replace an operator's recorded before-state.
SELECT config_key, config_value, description, updated_at
FROM public.ordelo_config
WHERE config_key IN ('ORDELO_APP_URL','RESTAURANT_MENU_APP_URL')
ORDER BY config_key;

INSERT INTO public.ordelo_config (config_key, config_value, description)
VALUES ('ORDELO_APP_URL','https://rider-agent-test.ordelo.app','URL for Ordelo app'),
       ('RESTAURANT_MENU_APP_URL','https://restaurant-test.ordelo.app','URL for restaurant frontend')
ON CONFLICT (config_key) DO UPDATE
SET config_value=EXCLUDED.config_value, updated_at=CURRENT_TIMESTAMP
RETURNING config_key, config_value;
