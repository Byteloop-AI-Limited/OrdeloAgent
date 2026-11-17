INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('STRK_APP_URL', 'https://elas-agg.ordelo.app', 'URL for ELAS app') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('STRK_DEFAULT_COLLECTION_PICKUP_TIME', '30', 'Minutes after order creation for collection pickup when configured auto-accept is enabled or restaurant confirmation times out; manual pickup selection is separate') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('STRK_DEFAULT_DELIVERY_PICKUP_TIME', '30', 'Minutes after order creation for delivery pickup when configured auto-accept is enabled or restaurant confirmation times out; manual pickup selection is separate') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;


INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('STRK_DELIVERY_TIMEOUT_TIME', '5', 'Minutes since order creation (or latest redispatch) before an unassigned delivery is marked timedout, only after all vehicle types have timed out; not a rider offer timeout') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('STRK_RESTAURANT_CONFIRMATION_TIMEOUT_TIME', '3', 'Minutes since order creation before unanswered delivery or collection confirmation (including accepted orders without a pickup time) is marked restaurant_timedout; checked every 10 seconds') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;


INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('STRK_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION', 'decline', 'What silence means when the confirmation times out: decline = order declined (auto_decline, customer told, payment cancelled); anything else or no row = auto-accepted (restaurant_timedout). Per restaurant only') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;


INSERT INTO public.ordelo_config (config_key, config_value, description)
VALUES ('STRK_TGRAM_ORDER_ALERT_OFFSETS_SECS', '0,15,30,45,60,75,85', 'Seconds after order creation to send or refresh the Telegram admin order card while restaurant confirmation is unanswered; stops on decision or timeout; checked every 5 seconds')
-- VALUES ('STRK_TGRAM_ORDER_ALERT_OFFSETS_SECS', '0', 'STRK override: seconds after a new order at which the Telegram order card is (re)sent.')
ON CONFLICT (config_key)
DO UPDATE SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;


select * from ordelo_config where config_key like '%STRK%' order by config_key;
select * from ordelo_config where config_key like '%BNAT%' order by config_key;
select * from ordelo_config where config_key like '%ELAS%' order by config_key;

update ordelo_config
set config_key = 'Z_ELAS_PICKUP_DEFAULT_TIME'
where config_key = 'ELAS_PICKUP_DEFAULT_TIME';

SELECT rest_ref, auto_accept FROM public.restaurant_master WHERE rest_ref = 'STRK';

SELECT
    rm.rest_ref,
    rm.auto_accept,
    specific.config_value AS restaurant_delivery_pickup_minutes,
    global.config_value AS global_delivery_pickup_minutes
  FROM restaurant_master rm
  LEFT JOIN ordelo_config specific
    ON specific.config_key = rm.rest_ref || '_DEFAULT_DELIVERY_PICKUP_TIME'
  LEFT JOIN ordelo_config global
    ON global.config_key = 'DEFAULT_DELIVERY_PICKUP_TIME'
  WHERE rm.rest_ref = 'BNAT';
