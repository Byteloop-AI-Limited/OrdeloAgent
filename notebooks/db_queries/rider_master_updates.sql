-- Master data maintenance for restaurant_master, rider_master, and customer_master.
-- Consolidated from CommonQueries.sql and config_updates.sql.
select * from rider_registrations;

select * from ordelo_config where config_key like '%_APP_URL';
select admins,* from restaurant_master where rest_ref='ELAS';
select * from rider_master order by is_in_shift desc, shift_response_dtts desc, status asc;

select * from cust_rest_map;
-- Run before 11 am
update rider_master set 
is_in_shift=false
;
-- , shift_response_dtts=now();
-- , town='dummy'
-- where town='Salisbury';

update rider_master set is_in_shift=true, town ='Salisbury', vehicle_type='bicycle' where rider_name='Lohith';
update rider_master set is_in_shift=true, town ='Salisbury', vehicle_type='bicycle' where rider_name='Rahul';

-- Prod setup
update rider_master set town ='Salisbury' where town='dummy';

-- Test setup
update rider_master set town ='dummy' where town='Salisbury';
update rider_master set town='Salisbury', is_in_shift=true where rider_name in ('Lohith');

-- delete from rider_master where rider_name='Muhibur';
select phone as rider_id,  from rider_registrations;
-- select 18+119.67;
INSERT INTO rider_master (rider_id, rider_name, vehicle_type, town, status, is_in_shift, priority)
VALUES
  -- ('447438568101', 'Rishi',      'car', 'Salisbury', 'active', FALSE, 1),
  -- ('447444198621', 'Ganesh',     'car', 'Salisbury', 'active', FALSE, 1),
  -- ('447469849539', 'Bokul',      'car', 'Salisbury', 'active', FALSE, 1),
  -- ('447473101040', 'Suraj',      'car', 'Salisbury', 'active', FALSE, 1),
  -- ('447305473427', 'Jamie',      'car', 'Salisbury', 'active', FALSE, 1),
  -- ('447853175864', 'Rangaswamy', 'car', 'Salisbury', 'active', FALSE, 1),
  -- ('447909510536', 'Nikhil',     'car', 'Salisbury', 'active', FALSE, 1),
  -- ('447448440754', '10hith',     'scooter', 'Orpington', 'active', FALSE, 1)
  -- ('447393103339', 'Ain',     'car', 'Salisbury', 'active', FALSE, 1),
  -- ('447927803163', 'Muhibur',     'scooter', 'Salisbury', 'active', FALSE, 1)
 ('447919202938', 'Bloop',     'scooter', 'Salisbury', 'active', FALSE, 1)
;

update rider_master set status='inactive' where rider_name in ('Lohith', 'Suraj', 'Jamie', 'Ganesh');
update rider_master set status='active' where rider_name in ('Lohith');

-- delete from rider_master where rider_id = '447429702917';