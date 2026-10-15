select * from ordelo_config where config_key like '%_APP_URL';
select * from ordelo_config where config_key like 'RESTAURANT_MENU%';
select * from ordelo_config where config_key like '%TIMEOUT%';

select * from ordelo_config where config_key like '%ORDELO%';
select * from ordelo_config where config_key like '%rider%';
select * from ordelo_config where config_key like '%ELAS%';
select * from ordelo_config where config_key like '%SIMULATE%';
select * from ordelo_config where config_key like '%MENU%';
select * from ordelo_config where config_key like '%BNAT%';

-- Reset cache
SELECT * FROM ordelo_post('ORDELO_APP_URL', '/restaurant-base-url-cache/reset');
SELECT config_value FROM ordelo_config WHERE config_key='WEB_STOREFRONT_URL';

-- Test Setup
UPDATE ordelo_config SET config_value = 'true', updated_at = now() WHERE config_key = 'ENABLE_SIMULATE_PAYMENT';
update ordelo_config set config_value = 'https://rider-agent-test.ordelo.app' where config_key = 'ORDELO_APP_URL'; 
update ordelo_config set config_value = 'https://restaurant-test.ordelo.app' where config_key = 'RESTAURANT_MENU_APP_URL'; 
update ordelo_config set config_value = 'https://restaurant-test.ordelo.app' where config_key = 'WEB_STOREFRONT_URL'; 

update ordelo_config set config_value = 'https://rest-agent-test.ordelo.app' where config_key = 'BNAT_APP_URL';
update ordelo_config set config_value = 'https://rest-agent-test.ordelo.app' where config_key = 'ELAS_APP_URL';
update ordelo_config set config_value = 'https://rest-agent-test.ordelo.app' where config_key = 'SFCS_APP_URL';
update ordelo_config set config_value = 'https://wren-agg-test.ordelo.app' where config_key = 'WREN_APP_URL';
--
-- Revert to production setup;

UPDATE ordelo_config SET config_value = 'false', updated_at = now() WHERE config_key = 'ENABLE_SIMULATE_PAYMENT';

update ordelo_config set config_value = 'https://rider-agent.ordelo.app' where config_key = 'ORDELO_APP_URL';
update ordelo_config set config_value = 'https://restaurant.ordelo.app' where config_key = 'RESTAURANT_MENU_APP_URL'; 
update ordelo_config set config_value = 'https://restaurant.ordelo.app' where config_key = 'WEB_STOREFRONT_URL'; 

update ordelo_config set config_value = 'https://bnat-agent.fly.dev/' where config_key = 'BNAT_APP_URL';
update ordelo_config set config_value = 'https://elas-agg.ordelo.app' where config_key = 'ELAS_APP_URL';
update ordelo_config set config_value = 'https://sfcs-agent.fly.dev' where config_key = 'SFCS_APP_URL';
SELECT * FROM ordelo_post('ORDELO_APP_URL', '/restaurant-base-url-cache/reset', 'rest_ref=ELAS');

select * from ordelo_config where config_key like 'ELAS_MENU_URL';

delete from ordelo_config where config_key='ELAS_MENU_APP_URL';

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
select * from ordelo_config where config_key like '%over%';
-- Debugging option
INSERT INTO ordelo_config (config_key, config_value, description)
-- VALUES ('overwatch_list', '447448440754,447424334783', 'list of numbers to alert')
VALUES ('overwatch_list', '447448440754', 'list of numbers to alert')
ON CONFLICT (config_key) 
DO UPDATE SET config_value = '123';
-- DO UPDATE SET config_value = '447446933210';
-- DO UPDATE SET config_value = '447448440754,447446933210';


select * from ordelo_config where config_key in ('ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS', 'ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS', 'rider_alert_to_overwatch_pickup_intervals', 'rider_alert_to_overwatch_pickup_intervals');



INSERT INTO ordelo_config (config_key, config_value, description)
VALUES
  ('ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS',
   '-15,-5,2,5,7',
   'Signed minutes around delivery_summary.pickup_time at which to alert a rider who has not yet collected; negative = before pickup, positive = after. Blank disables awaiting-pickup rider alerts.'),
  ('ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS',
   '30,45',
   'Minutes after delivery_summary.pickup_time at which to chase a rider who has collected but not delivered. Blank disables in-transit rider alerts.'),
  ('rider_alert_to_overwatch_pickup_intervals',
   '10',
   'Minutes past delivery_summary.pickup_time at which to alert overwatch and restaurant admins that a rider has still not collected. Blank disables.'),
  ('rider_alert_to_overwatch_delivery_intervals',
   '30',
   'Minutes past delivery_summary.pickup_time at which to alert overwatch and restaurant admins that a collected order is still undelivered. Blank disables.')
ON CONFLICT (config_key) DO NOTHING

SELECT * FROM ordelo_post('SFCS_APP_URL', '/internal/cache/reset', 'scope=all');

-- After changing overwatch_list, reset each deployed Restaurant Application.
SELECT * FROM ordelo_post('SFCS_APP_URL', '/internal/cache/reset', 'scope=overwatch');
SELECT * FROM ordelo_post('BNAT_APP_URL', '/internal/cache/reset', 'scope=overwatch');

select * from ordelo_config where config_key = 'overwatch_list';

INSERT INTO ordelo_config (config_key, config_value)
VALUES ('TERMINATE_STALE_ACTIVE_THREADS', '5')
ON CONFLICT (config_key) 
DO UPDATE SET config_value = '5';


select * from ordelo_config where config_key like 'ELAS%' OR config_key like 'CHK%';

-- Debugging option
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('CHKS_DELIVERY_TIMEOUT_TIME', '5', 'Timeout in minutes for delivery_summary status transition to timedout')
ON CONFLICT (config_key) 
DO UPDATE SET config_value = '5';

UPDATE ordelo_config 
SET config_value = '5'
WHERE config_key = 'ELAS_DELIVERY_TIMEOUT_TIME';

UPDATE ordelo_config 
SET config_value = '30'
WHERE config_key = 'ELAS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME';

-- delete from ordelo_config where config_key = 'ELAS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME';

select * from ordelo_config where config_key = 'ELAS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME';

SELECT (EXTRACT(EPOCH FROM (NOW() - date(now()-interval '3 seconds'))) / 60) > COALESCE(
          (SELECT config_value::numeric FROM ordelo_config 
           WHERE config_key = 'ELAS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1), (SELECT config_value::numeric FROM ordelo_config WHERE config_key = 'RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1), 5);

-- Debugging option
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('CHKS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME', '.5', 'Timeout in minutes for delivery_summary status transition to timedout')
ON CONFLICT (config_key) 
DO UPDATE SET config_value = '.5';

select * from rider_registrations;

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
VALUES ('ORDELO_MENU_APP_URL', 'https://restaurant.ordelo.app', 'URL for ordelo restaurant dashboard') ON CONFLICT (config_key) DO
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

select * from ordelo_config where config_key like '%SFCS%';

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



INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('ENABLE_SIMULATE_PAYMENT', 'true', 'restaurant-frontend: show Simulate payment on TEST3100 orders')
ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = now();

-- Onboarding new restaurant
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('SFCS_APP_URL', 'https://elas-agg-test.ordelo.app', 'URL for Southern Fried Chicken app') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description;

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('SFCS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME', '.5', 'Timeout in minutes for delivery_summary status transition to timedout') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description;

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('SFCS_RESTAURANT_CONFIRMATION_TIMEOUT_TBD', '0.25', 'Default minutes to wait for restaurant confirmation before defaulting to max prep time') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description;

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('SFCS_DEFAULT_DELIVERY_PICKUP_TIME', '30', 'SFCS delivery pickup default override') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('SFCS_DEFAULT_COLLECTION_PICKUP_TIME', '30', 'SFCS takeaway pickup default override') ON CONFLICT (config_key) DO
UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description;

-- delete from ordelo_config where config_key = 'DELIVERY_PICKUP_DEFAULT_TIME';
-- INSERT INTO ordelo_config (config_key, config_value, description)
-- VALUES
--   ('DEFAULT_COLLECTION_PICKUP_TIME',          '30', 'Default pickup time in minutes from order time when takeaway confirmation times out'),
--   ('DEFAULT_DELIVERY_PICKUP_TIME', '30', 'Default pickup time in minutes from order time when delivery confirmation times out')
-- ON CONFLICT (config_key) DO NOTHING;

-- -- Restaurant-specific overrides (insert per restaurant as needed, e.g. SFCS)
-- INSERT INTO ordelo_config (config_key, config_value, description)
-- VALUES
--   ('ELAS_PICKUP_DEFAULT_TIME',          '35', 'Elas takeaway pickup default override'),
--   ('ELAS_DELIVERY_PICKUP_DEFAULT_TIME', '35', 'Elas delivery pickup default override')
-- ON CONFLICT (config_key) DO NOTHING;

-- Restaurant-specific overrides (insert per restaurant as needed, e.g. SFCS)
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES
  ('SFCS_DEFAULT_COLLECTION_PICKUP_TIME','15', 'SFCS takeaway pickup default override'),
  ('SFCS_DEFAULT_DELIVERY_PICKUP_TIME', '15', 'SFCS delivery pickup default override')
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description;


  INSERT INTO ordelo_config (config_key, config_value, description)
  VALUES ('TGRAM_REST_ADMIN_BOT_USERNAME', 'OrdeloRestaurantBot', 'Restaurant-admin Telegram bot')
  ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = now();

-- Restaurant-specific overrides (insert per restaurant as needed, e.g. SFCS)
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES
  ('CHKS_DEFAULT_COLLECTION_PICKUP_TIME','30', 'Chks takeaway pickup default override'),
  ('CHKS_DEFAULT_DELIVERY_PICKUP_TIME', '30', 'Chks delivery pickup default override')
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description;



INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('SFCS_DELIVERY_TIMEOUT_TIME', '5', 'Timeout in minutes for delivery_summary status transition to timedout')
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description;

select config_key, config_value, description from ordelo_config where config_key like '%SFCS%';
select config_key, config_value, description from ordelo_config where config_key like '%CHKS%';

-- update config_key to 17 where config_key is SFCS_DEFAULT_COLLECTION_PICKUP_TIME and SFCS_DEFAULT_DELIVERY_PICKUP_TIME
-- update ordelo_config set config_value='17' where config_key in ('SFCS_DEFAULT_COLLECTION_PICKUP_TIME', 'SFCS_DEFAULT_DELIVERY_PICKUP_TIME' );

-- Absolute essential configs for rest_ref
[
 {
  "config_key": "SFCS_APP_URL",
  "config_value": "https://sfcs-agg.ordelo.app",
  "description": "URL for Southern Fried Chicken app"
 },
 {
  "config_key": "SFCS_DEFAULT_COLLECTION_PICKUP_TIME",
  "config_value": "30",
  "description": "SFCS takeaway pickup default override"
 },
 {
  "config_key": "SFCS_DEFAULT_DELIVERY_PICKUP_TIME",
  "config_value": "30",
  "description": "SFCS delivery pickup default override"
 },
 {
  "config_key": "SFCS_DELIVERY_TIMEOUT_TIME",
  "config_value": "5",
  "description": "Timeout in minutes for delivery_summary status transition to timedout"
 },
 {
  "config_key": "SFCS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME",
  "config_value": ".5",
  "description": "Timeout in minutes for delivery_summary status transition to timedout"
 }
];
--  Web
INSERT INTO ordelo_config (config_key, config_value, description) VALUES
  ('PAYMENT_INBOX_ENABLED',      'false', 'ordelo-agg R1a: payment-complete applies each payment once (record_payment_authorised)'),
  ('ORDER_CREATE_RPC_ENABLED',   'false', 'ordelo-agg R1a: create order + items in one transaction (create_food_order_with_items)'),
  ('ENABLE_PAYMENT_TEST_ROUTES', 'false', 'ordelo-agg R1a: allow /payment-hooks/payment-complete-test (keep false in prod)')
ON CONFLICT (config_key) DO NOTHING;


-- reconciler
-- check orders created from now on
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('PAYMENT_INIT_RECONCILER_SINCE', now()::text,
        'ordelo-agg R1a: alert on paid orders with no summary, created after this time')
ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = now();

-- 
UPDATE ordelo_config
   SET config_value = 'true', updated_at = now()
 WHERE config_key = 'PAYMENT_INBOX_ENABLED';

UPDATE ordelo_config
   SET config_value = 'true', updated_at = now()
 WHERE config_key = 'ORDER_CREATE_RPC_ENABLED';

select * from ordelo_config where config_key='CUSTOMER_NOTIFIER_REST_REFS';


UPDATE ordelo_config
SET config_value = 'ELAS,BNAT',
    updated_at = now()
WHERE config_key = 'CUSTOMER_NOTIFIER_REST_REFS';

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES ('TEST_PAYMENT_REST_REFS', 'BNAT', 'ordelo-agg D32: restaurants that honour ?isTest3100=true')
ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = now();

UPDATE ordelo_config SET config_value = 'BNAT', updated_at = now() WHERE config_key = 'TEST_PAYMENT_REST_REFS';

INSERT INTO ordelo_config (config_key, config_value, description)
VALUES
  ('CUSTOMER_NOTIFIER_ENABLED', 'true',
   'Enable R1b customer notifier'),
  ('CUSTOMER_NOTIFIER_REST_REFS', 'CRMS',
   'Restaurants included in the notifier pilot')
ON CONFLICT (config_key) DO NOTHING;

UPDATE ordelo_config
SET config_value = 'BNAT,ELAS', updated_at = now()
WHERE config_key = 'TEST_PAYMENT_REST_REFS';

select * from ordelo_config where config_key='CUSTOMER_NOTIFIER_ENABLED';
CUSTOMER_NOTIFIER_REST_REFS;


INSERT INTO ordelo_config (config_key, config_value)
VALUES ('WEB_STOREFRONT_URL', 'https://restaurant-test.ordelo.app')
ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value;