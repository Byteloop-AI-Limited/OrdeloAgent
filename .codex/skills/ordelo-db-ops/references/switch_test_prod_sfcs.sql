-- ============================================================
-- SFCS: Verification Queries
-- ============================================================

select admins, * from restaurant_master where rest_ref = 'SFCS';

select * from ordelo_config where config_key like '%_APP_URL';

select * from rider_master where rider_name = 'Lohith';
-- ============================================================
-- SFCS: Test Setup
-- ============================================================

update restaurant_master
set admins = Array['447919202938'],
    rest_stale_active_threads_minutes = 10,
    restaurant_start_time = 11,
    restaurant_end_time = 21.30,
    city='dummy'
where rest_ref='SFCS';

update rider_master
set is_in_shift = true,
    town = 'dummy',
    vehicle_type = 'bicycle'
where rider_name = 'Lohith';

update ordelo_config
set config_value = 'https://rider-agent-test.ordelo.app'
where config_key = 'ORDELO_APP_URL';


-- ============================================================
-- SFCS: Production Setup
-- ============================================================

update restaurant_master
set admins = Array['447448440754'],
    rest_stale_active_threads_minutes = 10,
    restaurant_start_time = 12,
    restaurant_end_time = 21.30,
    city='Salisbury'
where rest_ref = 'SFCS';

update rider_master
set is_in_shift = true,
    town = 'Salisbury',
    vehicle_type = 'bicycle'
where rider_name = 'Lohith';

update ordelo_config
set config_value = 'https://rider-agent.ordelo.app'
where config_key = 'ORDELO_APP_URL';
