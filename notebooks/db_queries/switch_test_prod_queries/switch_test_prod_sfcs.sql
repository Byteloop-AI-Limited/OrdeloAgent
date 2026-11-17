-- ============================================================
-- SFCS: Verification Queries
-- ============================================================

select admins, city, * from restaurant_master; 
select admins, city, * from restaurant_master where rest_ref in ('SFCS'); 

select * from ordelo_config where config_key like '%SFCS_APP_URL';

select * from rider_master where rider_name in ('Lohith', 'Rahul', 'Bloop');
select * from rider_master where is_in_shift = true;
-- ============================================================
-- SFCS: Test Setup
-- ============================================================
DO $$
BEGIN
    UPDATE restaurant_master
    SET admins = ARRAY['447919202938'],
        rest_stale_active_threads_minutes = 10,
        city = 'dummy',
        service_hours_json = '{
            "mon": [["18:00", "24:00"]],
            "tue": [["00:00", "24:00"]],
            "wed": [["18:00", "24:00"]],
            "thu": [["12:00", "24:00"]],
            "fri": [["18:00", "24:00"]],
            "sat": [["18:00", "25:00"]],
            "sun": [["18:00", "21:00"]]
        }'::jsonb
    WHERE rest_ref = 'SFCS';

    UPDATE sfcs_menu
    SET title = 'TEST 3101',
        description = 'Test item',
        availability = 'in stock',
        price = 10.00,
        currency = 'GBP',
        branch_link = 'https://sfc-salisbury.co.uk',
        image_link = 'https://ordelo-restaurants.s3.eu-west-2.amazonaws.com/sfcs/Triple+Mixed+Bucket.jpg',
        branch_name = 'Salisbury',
        category = 'Bucket Meal',
        addons = '{}'::jsonb
    WHERE sku = 'test_3101';

    IF NOT FOUND THEN
        INSERT INTO sfcs_menu (
            title, sku, description, availability, price, currency,
            branch_link, image_link, branch_name, category, addons
        )
        VALUES (
            'TEST 3101', 'test_3101', 'Test item', 'in stock', 10.00, 'GBP',
            'https://sfc-salisbury.co.uk',
            'https://ordelo-restaurants.s3.eu-west-2.amazonaws.com/sfcs/Triple+Mixed+Bucket.jpg',
            'Salisbury', 'Bucket Meal', '{}'::jsonb
        );
    END IF;

    -- UPDATE ordelo_config
    -- SET config_value = 'https://rest-agent-test.ordelo.app'
    -- WHERE config_key = 'SFCS_APP_URL';

    update rider_master
    set is_in_shift = true,
        town = 'dummy',
        vehicle_type = 'car'
    where rider_name = 'lohith';
    
    -- Cache reset call.
    PERFORM ordelo_post('ORDELO_APP_URL', '/internal/cache/reset');

END;
$$;



-- select enquire_admin_availability(ARRAY['SFCS']);
-- ============================================================
-- SFCS: Production Setup
-- ============================================================

-- '447827180109' - Mi
-- '447769081769' - SFCS Admin number2
-- '447312083527' - Srj
-- '447446933210' - Rh
-- '447919202938' - Bl

DO $$
BEGIN
    UPDATE restaurant_master
    SET admins = ARRAY['447446933210', '447919202938', '447827180109', '447769081769', '447312083527'],
        rest_stale_active_threads_minutes = 10,
        city = 'Salisbury',
        service_hours_json = '{
            "mon": [["11:30", "14:00"], ["16:00", "23:00"]],
            "tue": [["11:30", "14:00"], ["16:00", "23:00"]],
            "wed": [["11:30", "14:00"], ["16:00", "23:00"]],
            "thu": [["11:30", "14:00"], ["16:00", "23:00"]],
            "fri": [["11:30", "14:00"], ["16:00", "24:00"]],
            "sat": [["11:30", "14:00"], ["16:00", "24:00"]],
            "sun": [["11:30", "14:00"], ["16:00", "23:00"]]
        }'::jsonb
    WHERE rest_ref = 'SFCS';

    DELETE FROM sfcs_menu
    WHERE title = 'TEST 3101' AND sku = 'test_3101';

    UPDATE rider_master
    SET is_in_shift = true,
        town = 'Salisbury',
        vehicle_type = 'bicycle'
    WHERE rider_name = 'Lohith';

    -- Cache reset call.
    PERFORM ordelo_post('ORDELO_APP_URL', '/internal/cache/reset');

END;
$$;

select * from sfcs_menu where id='100'limit 1 ;

update elas_menu
set title = 'Naan'
where title='TEST3100';
-- 

UPDATE ordelo_config
SET config_value = 'https://sfcs-agent.fly.dev'
WHERE config_key = 'SFCS_APP_URL';


