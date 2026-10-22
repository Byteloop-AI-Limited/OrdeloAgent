-- Master data maintenance for restaurant_master, rider_master, and customer_master.

-- Consolidated from CommonQueries.sql and config_updates.sql.
select * from rider_registrations order by inserted_at desc;
select * from rider_master where town='Orpington' and status='active' order by shift_response_dtts desc, is_in_shift desc, status;

select * from rider_master;


select * from ordelo_config where config_key like '%_APP_URL';

select admins,* from restaurant_master where rest_ref='ELAS';
select admins,* from restaurant_master where rest_ref='SFCS';
select * from rider_master where town='Orpington' and is_in_shift;
select * from rider_master where date_trunc('second', shift_response_dtts)::time > time '11:00:00' and rider_id not in ('447448440754', '447446933210') order by is_in_shift desc, shift_response_dtts desc, status asc;

select * from public.bnat_menu;
-- , town='dummy'
-- where town='Salisbury';

update rider_master set is_in_shift=true, town ='Salisbury', vehicle_type='car' where rider_name='Lohith';
update rider_master set is_in_shift=true, town ='Dummy', vehicle_type='car' where rider_name='Rahul';

update rider_registrations set bank_account_name='REHAN ALI AWAN'
where id=42;
-- make this riders status=inactive
update rider_master set status='inactive', is_in_shift=false where rider_name in ('Steven', 'Dhruva', 'Rakesh');

SELECT public.enquire_shift_availability();
select enquire_admin_availability(ARRAY['ELAS']);
-- Prod setup
update rider_master set town ='Salisbury' where town='dummy';

-- Test setup
update rider_master set town='Salisbury', is_in_shift=true where rider_name in ('Lohith');
update rider_master set town='dummy', is_in_shift=true where rider_name in ('Lohith');

-- delete from rider_master where rider_name='Muhibur';
-- Remove leading + and spaces from phone number
select distinct replace(replace(phone, '+', ''), ' ', '') as rider_id, SPLIT_PART(full_name, ' ', 1) as rider_name, vehicle_type, area as town, false as is_in_shift, 'active' as status, 1 as priority from rider_registrations where area='Orpington';


INSERT INTO rider_master (rider_id, rider_name, vehicle_type, town, status, is_in_shift, priority)
VALUES
  ('447495654065', 'Majid',          'scooter', 'Orpington', 'active', FALSE, 1),
  ('447554466043', 'Dhruva',         'scooter', 'Orpington', 'active', FALSE, 1),
  ('447578401831', 'Rakesh',         'car',     'Orpington', 'active', FALSE, 1),
  ('447747200220', 'Amar',           'scooter', 'Orpington', 'active', FALSE, 1),
  ('447765522420', 'Rehan',          'scooter', 'Orpington', 'active', FALSE, 1),
  ('447768519536', 'Leonardo',       'scooter', 'Orpington', 'active', FALSE, 1),
  ('447823807404', 'Selvan', 'scooter', 'Orpington', 'active', FALSE, 1),
  ('447904796697', 'Hammad',         'car',     'Orpington', 'active', FALSE, 1),
  ('447961629376', 'Steven',         'car',     'Orpington', 'active', FALSE, 1),
  ('447984211602', 'Muhammad',       'scooter', 'Orpington', 'active', FALSE, 1)
;

-- ('447555687794', 'Marian', 'bike', 'Salisbury', 'active', FALSE, 1)
update rider_master set status='inactive' where rider_name in ('Marian', 'Luis', 'Suraj', 'Jamie', 'Ganesh', 'Ain', 'Agam');
update rider_master set is_in_shift=true where rider_name in ('Rishi', 'Abubakar', 'Bokul', 'Mohammed Hoque', 'Rangaswamy');

select * from rider_master where town='Orpington';
update rider_master set status='active', is_in_shift=true, channel='whatsapp' where rider_name='lohith';
update rider_master set status='active', is_in_shift=true, channel='telegram' where town='Orpington';