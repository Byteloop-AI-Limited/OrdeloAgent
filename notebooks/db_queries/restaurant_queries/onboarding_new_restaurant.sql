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
  lon,
  rest_stale_active_threads_minutes,
  restaurant_start_time,
  restaurant_end_time,
  service_hours_json,
  collection_commission
)
VALUES (
  'BNAT',
  '447919202938',
  'Burger Nation',
  'Palmkitchen26@gmail.com',
  ARRAY['447919202938'],
  '261',
  NULL,
  'High St.',
  'Orpington',
  'BR6 0NW',
  51.375083,
  0.099021,
  10,
  12,
  23.45,
  '{
    "mon": [["12:00", "23:45"]],
    "tue": [["12:00", "23:45"]],
    "wed": [["12:00", "23:45"]],
    "thu": [["12:00", "23:45"]],
    "fri": [["12:00", "23:45"]],
    "sat": [["12:00", "23:45"]],
    "sun": [["12:00", "23:45"]]
  }'::jsonb,
  0.04
)
ON CONFLICT (rest_ref) DO UPDATE
SET rest_id = EXCLUDED.rest_id,
    rest_name = EXCLUDED.rest_name,
    rest_email = EXCLUDED.rest_email,
    admins = EXCLUDED.admins,
    house_number = EXCLUDED.house_number,
    building_name = EXCLUDED.building_name,
    street_name = EXCLUDED.street_name,
    city = EXCLUDED.city,
    postcode = EXCLUDED.postcode,
    lat = EXCLUDED.lat,
    lon = EXCLUDED.lon,
    rest_stale_active_threads_minutes = EXCLUDED.rest_stale_active_threads_minutes,
    restaurant_start_time = EXCLUDED.restaurant_start_time,
    restaurant_end_time = EXCLUDED.restaurant_end_time,
    service_hours_json = EXCLUDED.service_hours_json,
    collection_commission = EXCLUDED.collection_commission;

INSERT INTO ordelo_config (
  config_key,
  config_value,
  description
)
VALUES
  (
    'BNAT_APP_URL',
    'https://bnat-agent.fly.dev',
    'URL for Burger Nation app'
  ),
  (
    'BNAT_DEFAULT_COLLECTION_PICKUP_TIME',
    '17',
    'BNAT takeaway pickup default override'
  ),
  (
    'BNAT_DEFAULT_DELIVERY_PICKUP_TIME',
    '17',
    'BNAT delivery pickup default override'
  ),
  (
    'BNAT_DELIVERY_TIMEOUT_TIME',
    '5',
    'Timeout in minutes for BNAT delivery_summary status transition to timedout'
  ),
  (
    'BNAT_RESTAURANT_CONFIRMATION_TIMEOUT_TIME',
    '.5',
    'Timeout in minutes before BNAT restaurant confirmation times out'
  )
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value,
    description = EXCLUDED.description,
    updated_at = CURRENT_TIMESTAMP;


select * from restaurant_master where rest_ref = 'BNAT';