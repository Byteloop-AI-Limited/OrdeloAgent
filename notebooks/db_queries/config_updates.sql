select *
from ordelo_config where config_key like '%_RESTAURANT_CONFIRMATION_TIMEOUT_TIME%';

update ordelo_config set config_value = 'https://elas-agg-test.ordelo.app' 
where config_key = 'ELAS_APP_URL';
update ordelo_config set config_value = 'https://rider-agent-test.ordelo.app'
where config_key = 'ORDELO_APP_URL';
update ordelo_config set config_value = 'https://elas-agg-test.ordelo.app' 
where config_key = 'WREN_APP_URL';
 
update ordelo_config set config_value = 'https://elas-agg.ordelo.app' 
where config_key = 'ELAS_APP_URL';
update ordelo_config set config_value = 'https://rider-agent.ordelo.app'
where config_key = 'ORDELO_APP_URL';

select * from rider_master;

update ordelo_config set config_value = 10
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

-- Debugging option
INSERT INTO ordelo_config (config_key, config_value)
VALUES ('ENABLE_TRIGGER_DEBUG_LOG', 'true')
ON CONFLICT (config_key) 
DO UPDATE SET config_value = 'true';

INSERT INTO ordelo_config (config_key, config_value)
VALUES ('TERMINATE_STALE_ACTIVE_THREADS', '5')
ON CONFLICT (config_key) 
DO UPDATE SET config_value = '5';


select * from ordelo_config where config_key like '%TIME%';

-- Debugging option
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('ELAS_DELIVERY_TIMEOUT_TIME', '5', 'Timeout in minutes for delivery_summary status transition to timedout')
ON CONFLICT (config_key) 
DO UPDATE SET config_value = '5';

UPDATE ordelo_config 
SET config_value = '5'
WHERE config_key = 'ELAS_DELIVERY_TIMEOUT_TIME';

UPDATE ordelo_config 
SET config_value = '30'
WHERE config_key = 'ELAS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME';

delete from ordelo_config where config_key = 'ELAS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME';

select * from ordelo_config where config_key = 'ELAS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME';

SELECT (EXTRACT(EPOCH FROM (NOW() - date(now()-interval '3 seconds'))) / 60) > COALESCE(
          (SELECT config_value::numeric FROM ordelo_config 
           WHERE config_key = 'ELAS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1), (SELECT config_value::numeric FROM ordelo_config WHERE config_key = 'RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1), 5);

-- Debugging option
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('ELAS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME', '.5', 'Timeout in minutes for delivery_summary status transition to timedout')
ON CONFLICT (config_key) 
DO UPDATE SET config_value = '.5';



UPDATE ordelo_config 
SET config_value = 'false'
WHERE config_key = 'ENABLE_TRIGGER_DEBUG_LOG';

select * from debug_log;
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
VALUES ('ORDELO_AGG_APP_URL', 'https://restaurant.ordelo.app', 'URL for ordelo restaurant dashboard') ON CONFLICT (config_key) DO
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
VALUES ('ELAS_RESTAURANT_CONFIRMATION_TIMEOUT', '0.25', 'Default minutes to wait for restaurant confirmation before defaulting to max prep time') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description;

-- Testing the config update
SELECT * FROM job_restaurant_confirmation_timeout('ELAS');

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

select * from restaurant_master;

update restaurant_master
set admins=ARRAY['447919202938']
where rest_ref='ELAS';

UPDATE rider_master
SET is_in_shift=false;
-- WHERE rider_name in ('Syama');

delete from rider_master where id=5;

SELECT 
*
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


select status, pickup_time, * from delivery_summary 
where order_number='ELAS-OROT-32' 
order by dtts desc;

update delivery_summary
set status='restaurant_unconfirmed'
where order_number='ELAS-OROT-32';


update delivery_summary
set status='restaurant_accept'
where order_number='ELAS-OROT-32';

select * from food_order
where order_number='ELAS-OROT-32';

SELECT config_value 
FROM ordelo_config 
WHERE config_key = 'ORDELO_APP_URL';


select * from restaurant_