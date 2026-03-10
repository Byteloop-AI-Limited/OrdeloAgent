select admins, * from restaurant_master where rest_ref='ELAS';
select admins, * from restaurant_master where rest_ref='CHKS';
select admins, * from restaurant_master where rest_ref='SFCS';

select admins,* from restaurant_master where rest_ref='ELAS';

select init_delivery('447448440754', 'WREN-AEHO-21');
select * from thread;

-- update restaurant_master set city='Orpington' where rest_ref='WREN';

-- Production Setup - ELAS
update restaurant_master 
set admins=Array['447448440754', '447446933210','447901518136','447914844933', '447917912646'],
    rest_stale_active_threads_minutes=10,
    restaurant_start_time=12,
    restaurant_end_time=21.30
where rest_ref='ELAS';

-- Test Setup - ELAS
update restaurant_master 
set admins=Array['447919202938'],
    rest_stale_active_threads_minutes=10,
    restaurant_start_time=11,
    restaurant_end_time=21.30
where rest_ref in ('ELAS', 'CHKS');

select * from restaurant_master where rest_ref='ELAS';
restaurant_master
update restaurant_master
set admins=Array['447448440754','447446933210', '447919202938'] where rest_ref='ELAS';

447914844933 - Unni
447901518136 - Bineesh
447917912646 - Dinesh
447448440754 - basal
447446933210 - rahul
447919202938 - bloop business account
447424334783 - Chaitra
;

-- ELAS lat=51.0726635283769, lon=-1.79717268758398
-- WREN lat=51.3601711280004, lon=0.0907554051501591
update restaurant_master set lat = 51.0726635283769, lon = -1.79717268758398 
 where rest_ref = 'ELAS';
update restaurant_master set lat = 51.3601711280004, lon = 0.0907554051501591
 where rest_ref = 'ELAS';

INSERT INTO restaurant_master (
  admins,
  rest_ref,
  rest_id,
  rest_name,
  rest_email,
  house_number,
  building_name,
  street_name,
  city,
  postcode,
  lat,
  lon,
  dt,
  dtts,
  rest_stale_active_threads_minutes,
  restaurant_start_time,
  restaurant_end_time
)
VALUES (
  ARRAY['447919202938'],
  'CHKS',
  '447914841234',
  'Wings and Things',
  NULL,
  'Mill Stream Approach',
  NULL,
  'Castle St',
  'Salisbury',
  'SP1 3TA',
  51.0726635283769,
  -1.79717268758398,
  '2025-10-17',
  '2025-10-17 20:45:29.547521+00',
  10,
  11,
  21.3
);

INSERT INTO restaurant_master (
  admins,
  rest_ref,
  rest_id,
  rest_name,
  rest_email,
  house_number,
  building_name,
  street_name,
  city,
  postcode,
  lat,
  lon,
  dt,
  dtts,
  rest_stale_active_threads_minutes,
  restaurant_start_time,
  restaurant_end_time
)
VALUES (
  ARRAY['447919202938'],
  'SFCS',
  '447448441234',
  'Southern Fried Chicken',
  'info@sfc-salisbury.co.uk',
  '66',
  NULL,
  'Castle Street',
  'Salisbury',
  'SP1 3TS',
  51.07176126077215, 
  -1.79609677126815,
  '2026-03-09',
  '2026-03-09 20:40:29.547521+00',
  10,
  11,
  21.3
);