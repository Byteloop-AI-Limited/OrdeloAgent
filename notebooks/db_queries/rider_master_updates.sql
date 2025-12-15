-- Master data maintenance for restaurant_master, rider_master, and customer_master.
-- Consolidated from CommonQueries.sql and config_updates.sql.
select * from rider_master;
insert into rider_master(rider_id, rider_name, vehicle_type, town, status, is_in_shift, priority);

select phone as rider_id,  from rider_registrations;

INSERT INTO rider_master (rider_id, rider_name, vehicle_type, town, status, is_in_shift, priority)
VALUES
  ('447438568101', 'Rishi',      'car', 'Salisbury', 'active', TRUE, 1),
  ('447444198621', 'Ganesh',     'car', 'Salisbury', 'active', TRUE, 1),
  ('447469849539', 'Bokul',      'car', 'Salisbury', 'active', TRUE, 1),
  ('447909510560', 'Nikhil',     'car', 'Salisbury', 'active', TRUE, 1),
  ('447473101040', 'Suraj',      'car', 'Salisbury', 'active', TRUE, 1),
  ('447305473427', 'Jamie',      'car', 'Salisbury', 'active', TRUE, 1),
  ('447853175864', 'Rangaswamy', 'car', 'Salisbury', 'active', TRUE, 1);
