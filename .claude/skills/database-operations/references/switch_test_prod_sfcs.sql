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
set admins = Array['447919202938'],
-- set admins = Array['447448440754'],
    rest_stale_active_threads_minutes = 10,
    restaurant_start_time = 18,
    restaurant_end_time = 24,
    city='dummy'
where rest_ref='SFCS';

update ordelo_config set config_value = 'https://rest-agent-test.ordelo.app' where config_key = 'SFCS_APP_URL';

update rider_master
set is_in_shift = true,
    town = 'dummy',
    vehicle_type = 'bicycle'
where rider_name = 'Lohith';

select enquire_admin_availability(ARRAY['ELAS', 'SFCS']);
-- ============================================================
-- SFCS: Production Setup
-- ============================================================

update restaurant_master
set admins = Array['447919202938','447827180109', '447774458613'],
    rest_stale_active_threads_minutes = 10,
    restaurant_start_time = 14,
    restaurant_end_time = 23.59,
    city='Salisbury'
where rest_ref = 'SFCS';

update ordelo_config set config_value = 'https://sfcs-agg.ordelo.app' where config_key = 'SFCS_APP_URL';

update rider_master
set is_in_shift = true,
    town = 'Salisbury',
    vehicle_type = 'bicycle'
where rider_name = 'Lohith';
