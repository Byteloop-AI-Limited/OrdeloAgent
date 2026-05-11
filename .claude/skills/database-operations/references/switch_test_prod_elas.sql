-- ============================================================
-- ELAS: Verification Queries
-- ============================================================

select admins, city, restaurant_start_time, * from restaurant_master where rest_ref in ('ELAS', 'CHKS');

select * from ordelo_config where config_key like '%_APP_URL';

select * from rider_master where rider_name = 'Lohith';
-- ============================================================
-- ELAS: Test Setup
-- ============================================================

update restaurant_master
set admins = Array['447919202938'],
    rest_stale_active_threads_minutes = 10,
    restaurant_start_time = 11,
    -- restaurant_end_time = 21.30,
    restaurant_end_time = 24,
    city='dummy'
where rest_ref in ('ELAS', 'CHKS');

update rider_master
set is_in_shift = true,
    town = 'dummy',
    vehicle_type = 'bicycle'
where rider_name = 'Lohith';

update ordelo_config set config_value = 'https://rest-agent-test.ordelo.app' where config_key = 'ELAS_APP_URL';

-- ============================================================
-- ELAS: Production Setup
-- ============================================================

update restaurant_master
set admins = Array['447448440754', '447446933210','447901518136','447914844933', '447917912646', '447909488602'],
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
    vehicle_type = 'bicycle'
where rider_name = 'Lohith';

update ordelo_config set config_value = 'https://elas-agg.ordelo.app' where config_key = 'ELAS_APP_URL';

-- Cache reset calls, Should be run everytime after changing the app URL
SELECT * FROM ordelo_post('ELAS_APP_URL', '/restaurant-base-url-cache/reset', 'rest_ref=ELAS');
SELECT * FROM ordelo_post('ELAS_APP_URL', '/restaurant-master-cache/reset',   'rest_ref=ELAS');
