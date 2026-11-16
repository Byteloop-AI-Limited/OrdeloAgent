-- ============================================================
-- SFCS: Verification Queries
-- ============================================================

select admins, city, * from restaurant_master; 
select admins, city, * from restaurant_master where rest_ref in ('SFCS'); 

select * from ordelo_config where config_key like '%SFCS_APP_URL';
select * from strk_menu where title='TEST3101' and sku='test_3101';
select * from rider_master where rider_name in ('lohith', 'Rahul', 'Bloop');
select * from rider_master where is_in_shift = true;
-- ============================================================
-- STRK: Test Setup
-- ============================================================
DO $$
BEGIN
    UPDATE restaurant_master
    SET admins = ARRAY['447919202938','447448440754'],
        rest_stale_active_threads_minutes = 10,
        city = 'dummy',
        service_hours_json = '{
            "mon": [["10:00", "24:00"]],
            "tue": [["00:00", "24:00"]],
            "wed": [["10:00", "24:00"]],
            "thu": [["10:00", "24:00"]],
            "fri": [["10:00", "24:00"]],
            "sat": [["10:00", "25:00"]],
            "sun": [["10:00", "21:00"]]
        }'::jsonb
    WHERE rest_ref = 'STRK';

    INSERT INTO strk_menu (
        id, title, sku, description, availability, price, currency,
        branch_link, branch_name, category, addons
    )
    SELECT
        (SELECT COALESCE(MAX(id), 0) + 1 FROM strk_menu),
        'TEST3100', 'test_3100', 'Test item', 'in stock', 10.00, 'GBP',
        'https://strikersbar.com/', 'Orpington', 'Star Burgers', '{}'::jsonb
    WHERE NOT EXISTS (SELECT 1 FROM strk_menu WHERE sku = 'test_3101');

    -- UPDATE ordelo_config
    -- SET config_value = 'https://rest-agent-test.ordelo.app'
    -- WHERE config_key = 'SFCS_APP_URL';

    update rider_master
    set is_in_shift = true,
        town = 'dummy',
        vehicle_type = 'car'
    where rider_name in ('lohith', 'lohithNwg');
    
    -- Cache reset call.
    PERFORM ordelo_post('ORDELO_APP_URL', '/internal/cache/reset');

END;
$$;



-- ============================================================
-- STRK: Production Setup
-- ============================================================
-- '447446933210' - Rh
-- '447919202938' - Bl
-- '447448440754' - lb

DO $$
BEGIN
    UPDATE restaurant_master
    SET admins = ARRAY['447446933210', '447919202938', '447448440754'],
        rest_stale_active_threads_minutes = 10,
        city = 'Orpington',
        service_hours_json = '{
            "mon": [["11:30", "14:00"], ["16:00", "23:00"]],
            "tue": [["11:30", "14:00"], ["16:00", "23:00"]],
            "wed": [["11:30", "14:00"], ["16:00", "23:00"]],
            "thu": [["11:30", "14:00"], ["16:00", "23:00"]],
            "fri": [["11:30", "14:00"], ["16:00", "24:00"]],
            "sat": [["11:30", "14:00"], ["16:00", "24:00"]],
            "sun": [["11:30", "14:00"], ["16:00", "23:00"]]
        }'::jsonb
    WHERE rest_ref = 'STRK';

    DELETE FROM strk_menu
    WHERE title = 'TEST3101';

    UPDATE rider_master
    SET is_in_shift = true,
        town = 'Orpington',
        vehicle_type = 'bicycle'
    where rider_name in ('lohith', 'lohithNwg');

    -- Cache reset call.
    PERFORM ordelo_post('ORDELO_APP_URL', '/internal/cache/reset');

END;
$$;

select * from sfcs_menu where id='100'limit 1 ;



UPDATE ordelo_config
SET config_value = 'https://sfcs-agent.fly.dev'
WHERE config_key = 'SFCS_APP_URL';
