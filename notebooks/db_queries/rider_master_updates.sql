-- Master data maintenance for restaurant_master, rider_master, and customer_master.
-- Consolidated from CommonQueries.sql and config_updates.sql.
select * from rider_registrations order by inserted_at desc;
select * from rider_master;
select * from ordelo_config where config_key like '%_APP_URL';

select admins,* from restaurant_master where rest_ref='ELAS';
select admins,* from restaurant_master where rest_ref='SFCS';
select * from rider_master;
select * from rider_master where date_trunc('second', shift_response_dtts)::time > time '11:00:00' and rider_id not in ('447448440754', '447446933210') order by is_in_shift desc, shift_response_dtts desc, status asc;

-- update rider_master set is_in_shift=true where town='Salisbury';
select * from cust_rest_map;
-- Run before 11 am
update rider_master set 
is_in_shift=false
;
-- , shift_response_dtts=now();
-- , town='dummy'
-- where town='Salisbury';

update rider_master set is_in_shift=true, town ='Salisbury', vehicle_type='car' where rider_name='Lohith';
update rider_master set is_in_shift=true, town ='dummy', vehicle_type='car' where rider_name='Rahul';

SELECT public.enquire_shift_availability();
select enquire_admin_availability(ARRAY['ELAS']);
-- Prod setup
update rider_master set town ='Salisbury' where town='dummy';

-- Test setup
update rider_master set town='Salisbury', is_in_shift=true where rider_name in ('Lohith');
update rider_master set town='dummy', is_in_shift=true where rider_name in ('Lohith');

-- delete from rider_master where rider_name='Muhibur';
select phone as rider_id,  from rider_registrations;
-- select 18+119.67;
INSERT INTO rider_master (rider_id, rider_name, vehicle_type, town, status, is_in_shift, priority)
VALUEr
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
--  ('447555982235', 'Luis', 'car', 'Salisbury', 'active', FALSE, 1)
('447555687794', 'Marian', 'bike', 'Salisbury', 'active', FALSE, 1)
;
-- ('447555687794', 'Marian', 'bike', 'Salisbury', 'active', FALSE, 1)
update rider_master set status='inactive' where rider_name in ('Marian', 'Luis', 'Suraj', 'Jamie', 'Ganesh', 'Ain', 'Agam');
update rider_master set is_in_shift=true where rider_name in ('Rishi', 'Abubakar', 'Bokul', 'Mohammed Hoque', 'Rangaswamy');

select * from rider_master where rider_name = 'Marian';


