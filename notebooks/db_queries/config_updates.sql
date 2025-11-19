select *
from ordelo_config;

update ordelo_config
set config_value = 'https://rider-agent.ordelo.app'
where config_key = 'ORDELO_APP_URL';

update ordelo_config
set config_value = 'https://agent.ordelo.app'
where config_key = 'ORDELO_APP_URL';


update ordelo_config
set config_value = 10
where config_key = 'DISPATCH_BATCH_SIZE_ELECTRIC_BIKE';


update ordelo_config
set config_value = 10
where config_key = 'DISPATCH_BATCH_SIZE_SCOOTER';


update ordelo_config
set config_value = 10
where config_key = 'DISPATCH_BATCH_SIZE_CAR';


update ordelo_config
set config_value = 10
where config_key = 'DISPATCH_BATCH_SIZE_BICYCLE';


INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('ELAS_APP_URL', 'https://elaib-agent.ordelo.app', 'URL for Salisbury app') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description;

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('ORDELO_APP_URL', 'https://agent.ordelo.app', 'URL for ordelo app') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description;

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('ORDELO_APP_URL', 'https://agent.ordelo.app', 'URL for ordelo app') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description;

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('LOCATION_ENABLE_TIME_INTERVAL', '1', 'Time interval in minutes for location enable') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description;

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('DELIVERY_TIMEOUT_TIME', '1', 'Timeout in minutes for delivery_summary status transition to timedout') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description;


INSERT INTO ordelo_config (config_key, config_value, description)
VALUES 
  ('RESTAURANT_CONFIRMATION_TIMEOUT', '5', 'Default minutes to wait for restaurant confirmation before defaulting to max prep time')
ON CONFLICT (config_key) DO NOTHING;

select *
from ordelo_config;

-- update restaurant master
update restaurant_master 
set lat = 51.359349, lon = 0.0904094
where rest_ref='WREN';

UPDATE rider_master
SET is_in_shift=false;
-- WHERE rider_name in ('Syama');

SELECT 
DISTINCT rider_id, rider_name 
FROM rider_master WHERE status='active' limit 10;

update rider_master set town='Salisbury'
where rider_id in ('447448440754', '447446933210')

select enquire_shift_availability();


INSERT INTO restaurant_master (
    rest_ref,
    rest_id,
    rest_name,
    rest_email,
    admins,
    house_number,
    building_name,
    street_name,
    city,
    postcode,
    lat,
    lon
)
VALUES (
    'ELAS',
    '447914844933',
    'Elai - Salisbury',
    NULL,
    ARRAY['447424334783', '447914844933'],
    'Mill Stream Approach',
    NULL,
    'Castle St',
    'Salisbury',
    'SP1 3TA',
    51.07266352837689,
    -1.797172687583984
);