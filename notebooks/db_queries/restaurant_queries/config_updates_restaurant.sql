INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('BNAT_APP_URL', 'https://elas-agg.ordelo.app', 'URL for ELAS app') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('BNAT_DEFAULT_COLLECTION_PICKUP_TIME', '30', 'BNAT collection pickup default override') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('BNAT_DEFAULT_DELIVERY_PICKUP_TIME', '30', 'BNAT delivery pickup default override') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;


INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('BNAT_DELIVERY_TIMEOUT_TIME', '10', 'Timeout in minutes for delivery_summary status transition to timedout') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('BNAT_RESTAURANT_CONFIRMATION_TIMEOUT_TIME', '0.5', 'Timeout in minutes for restaurant confirmation') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;


select * from ordelo_config where config_key like '%SFCS%' order by config_key;
select * from ordelo_config where config_key like '%BNAT%' order by config_key;
select * from ordelo_config where config_key like '%ELAS%' order by config_key;

update ordelo_config
set config_key = 'Z_ELAS_PICKUP_DEFAULT_TIME'
where config_key = 'ELAS_PICKUP_DEFAULT_TIME';


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
