-- ============================================================
-- SFCS: Verification Queries
-- ============================================================

select admins, city, * from restaurant_master where rest_ref = 'SFCS';

select * from ordelo_config where config_key like '%_APP_URL';

select * from rider_master where rider_name = 'Lohith';
-- ============================================================
-- SFCS: Test Setup
-- ============================================================

update restaurant_master
-- set admins = Array['447919202938', '447448440754'],
set admins = Array['447919202938'],
    rest_stale_active_threads_minutes = 10,
    city='dummy',
    service_hours_json = '{
  "mon": [["18:00", "24:00"]],
  "tue": [["18:00", "24:00"]],
  "wed": [["18:00", "24:00"]],
  "thu": [["18:00", "24:00"]],
  "fri": [["00:00", "24:00"]],
  "sat": [["18:00", "25:00"]],
  "sun": [["18:00", "21:00"]]
}'::jsonb
where rest_ref='SFCS';

update ordelo_config set config_value = 'https://rest-agent-test.ordelo.app' where config_key = 'SFCS_APP_URL';

-- Cache reset calls, Should be run everytime after changing the app URL
SELECT * FROM ordelo_post('SFCS_APP_URL', '/restaurant-base-url-cache/reset');
SELECT * FROM ordelo_post('SFCS_APP_URL', '/restaurant-master-cache/reset');

update rider_master
set is_in_shift = true,
    town = 'dummy',
    vehicle_type = 'bicycle'
where rider_name = 'Lohith';

select enquire_admin_availability(ARRAY['SFCS']);
-- ============================================================
-- SFCS: Production Setup
-- ============================================================

update restaurant_master
set admins = Array[ '447446933210','447919202938','447827180109', '447774458613', '447312083527'],
    rest_stale_active_threads_minutes = 10,
    city='Salisbury',
    service_hours_json = '{
  "mon": [["16:00", "24:00"]],
  "tue": [["16:00", "24:00"]],
  "wed": [["16:00", "24:00"]],
  "thu": [["16:00", "24:00"]],
  "fri": [["16:00", "24:00"]],
  "sat": [["16:00", "25:00"]],
  "sun": [["16:00", "25:00"]]
}'::jsonb
where rest_ref = 'SFCS';

update ordelo_config set config_value = 'https://sfcs-agg.ordelo.app' where config_key = 'SFCS_APP_URL';

update rider_master
set is_in_shift = true,
    town = 'Salisbury',
    vehicle_type = 'bicycle'
where rider_name = 'Lohith';


-- Cache reset calls, Should be run everytime after changing the app URL
SELECT * FROM ordelo_post('SFCS_APP_URL', '/restaurant-base-url-cache/reset');
SELECT * FROM ordelo_post('SFCS_APP_URL', '/restaurant-master-cache/reset');