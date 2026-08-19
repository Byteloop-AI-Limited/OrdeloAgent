-- ============================================================
-- ELAS: Verification Queries
-- ============================================================

select admins, city, restaurant_start_time, * from restaurant_master where rest_ref in ('ELAS', 'CHKS');

select * from ordelo_config where config_key like 'ELAS_APP_URL';

select * from rider_master where rider_name in ('Lohith', 'Bloop', 'Rahul');
-- ============================================================
-- ELAS: Test Setup
-- ============================================================
update ordelo_config set config_value = 'https://rest-agent-test.ordelo.app' where config_key = 'ELAS_APP_URL';

update restaurant_master
set admins = Array['447919202938'],
    rest_stale_active_threads_minutes = 10,
    restaurant_start_time = 11,
    service_hours_json = '{
  "mon": [["18:00", "24:00"]],
  "tue": [["18:00", "24:00"]],
  "wed": [["18:00", "24:00"]],
  "thu": [["18:00", "24:00"]],
  "fri": [["00:00", "24:00"]],
  "sat": [["18:00", "25:00"]],
  "sun": [["18:00", "21:00"]]
}'::jsonb,
    restaurant_end_time = 24,
    auto_accept = true,
    city='dummy'
where rest_ref in ('ELAS', 'CHKS');

update rider_master
set is_in_shift = true,
    town = 'dummy',
    vehicle_type = 'car'
where rider_name = 'Lohith';

update rider_master
set is_in_shift = true,
    town = 'dummy',
    vehicle_type = 'car'
where rider_name = 'Rahul';


update rider_master
set is_in_shift = true,
    town = 'dummy',
    vehicle_type = 'car'
where rider_name in ('Bloop');



-- ============================================================
-- ELAS: Production Setup
-- ============================================================
--  447901518136 - Bineesh
--  447914844933 - Unni
--  447770114931 - Raj
--  447424792533 - Muthukumaran
update restaurant_master
set admins = Array['447448440754', '447446933210','447901518136','447914844933', '447770114931', '447424792533'],
    rest_stale_active_threads_minutes = 10,
    city='Salisbury',
    service_hours_json = '{
        "mon": [["12:00", "22:00"]],
        "tue": [["12:00", "22:00"]],
        "wed": [["12:00", "22:00"]],
        "thu": [["12:00", "22:00"]],
        "fri": [["12:00", "22:00"]],
        "sat": [["12:00", "22:00"]],
        "sun": [["12:00", "21:00"]]
    }'::jsonb
where rest_ref in ('ELAS', 'CHKS');

update rider_master
set is_in_shift = true,
    town = 'Salisbury',
    vehicle_type = 'car'
where rider_name = 'Rahul';

update rider_master
set is_in_shift = true,
    town = 'Salisbury',
    vehicle_type = 'bicycle'
where rider_name = 'Lohith';

update ordelo_config set config_value = 'https://elas-agg.ordelo.app' where config_key = 'ELAS_APP_URL';

-- Cache reset calls, Should be run everytime after changing the app URL
SELECT * FROM ordelo_post('ELAS_APP_URL', '/restaurant-base-url-cache/reset', 'rest_ref=ELAS');
SELECT * FROM ordelo_post('ELAS_APP_URL', '/restaurant-master-cache/reset',   'rest_ref=ELAS');
