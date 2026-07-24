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
  "mon": [["11:30", "13:45"], ["16:00", "22:45"]],
  "tue": [["11:30", "13:45"], ["16:00", "22:45"]],
  "wed": [["11:30", "13:45"], ["16:00", "22:45"]],
  "thu": [["11:30", "13:45"], ["16:00", "22:45"]],
  "fri": [["11:30", "13:45"], ["16:00", "23:45"]],
  "sat": [["11:30", "13:45"], ["16:00", "23:45"]],
  "sun": [["11:30", "13:45"], ["16:00", "22:45"]]
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

'447827180109' - Mi
'447769081769' - SFCS Admin number2
'447312083527' - Srj
'447446933210' - Rh
'447919202938' - Bl;

update restaurant_master
set admins = Array[ '447446933210','447919202938','447827180109', '447769081769', '447312083527'],
    rest_stale_active_threads_minutes = 10,
    city='Salisbury',
    service_hours_json = '{
  "mon": [["11:30", "13:45"], ["16:00", "22:45"]],
  "tue": [["11:30", "13:45"], ["16:00", "22:45"]],
  "wed": [["11:30", "13:45"], ["16:00", "22:45"]],
  "thu": [["11:30", "13:45"], ["16:00", "22:45"]],
  "fri": [["11:30", "13:45"], ["16:00", "23:45"]],
  "sat": [["11:30", "13:45"], ["16:00", "23:45"]],
  "sun": [["11:30", "13:45"], ["16:00", "22:45"]]
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