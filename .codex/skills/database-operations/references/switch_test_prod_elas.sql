-- ============================================================
-- SFCS: Verification Queries
-- ============================================================

select admins, * from restaurant_master where rest_ref = 'ELAS';

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
where rest_ref in ('ELAS', 'CHKS');

update rider_master
set is_in_shift = true,
    town = 'dummy',
    vehicle_type = 'bicycle'
where rider_name = 'Lohith';


-- ============================================================
-- SFCS: Production Setup
-- ============================================================

update restaurant_master
set admins = Array['447448440754', '447446933210','447901518136','447914844933', '447917912646', '447909488602'],
    rest_stale_active_threads_minutes = 10,
    restaurant_start_time = 12,
    restaurant_end_time = 21.30,
    city='Salisbury'
where rest_ref in ('ELAS', 'CHKS');

update rider_master
set is_in_shift = true,
    town = 'Salisbury',
    vehicle_type = 'bicycle'
where rider_name = 'Lohith';
