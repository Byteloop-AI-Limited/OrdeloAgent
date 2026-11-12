-- CRDO restaurant_master INSERT for manual execution. Not executed by the agent. Run 00 first.
-- Confirmed by the user (2026-11-12): name, address 273 High Street Orpington BR6 0NW, phone 01689332664 (backend
-- registry and frontend only; not a column here), lat/lon 51.374745918702864, 0.09894222729275585, hours below.
-- Copied from STRK (live values read 2026-11-12): admins, auto_accept, collection_commission 0.1,
-- delivery/takeaway cutoffs 15, stale active-thread timeout 10.
-- rest_id 'CRDO01' follows STRK's 'STRK01'. rest_email is omitted (none supplied; must be nullable, see 00).
-- Hours: Mon-Fri 10:00-22:00, Sat-Sun 09:00-22:00 (Europe/London). Legacy start/end use the h.mm convention
-- for the widest window (9 and 22); the web uses service_hours_json.
-- Do not run twice: this is a plain INSERT, not an upsert.
INSERT INTO public.restaurant_master (
  rest_ref, rest_id, rest_name, admins,
  house_number, building_name, street_name, city, postcode, lat, lon,
  service_hours_json, delivery_order_cutoff_minutes, takeaway_order_cutoff_minutes,
  collection_commission, auto_accept, rest_stale_active_threads_minutes,
  restaurant_start_time, restaurant_end_time
) VALUES (
  'CRDO', 'CRDO01', 'Crispy Dosa', ARRAY['447448440754','447929843965','447446933210'],
  '273', NULL, 'High Street', 'Orpington', 'BR6 0NW', 51.374745918702864, 0.09894222729275585,
  '{"mon":[["10:00","22:00"]],"tue":[["10:00","22:00"]],"wed":[["10:00","22:00"]],"thu":[["10:00","22:00"]],"fri":[["10:00","22:00"]],"sat":[["09:00","22:00"]],"sun":[["09:00","22:00"]]}'::jsonb,
  15, 15,
  0.1, true, 10,
  9, 22
) RETURNING rest_ref, rest_id, rest_name, admins, city, postcode, lat, lon,
            service_hours_json, collection_commission, auto_accept;

SELECT rest_ref, rest_id, rest_name, admins, house_number, street_name, city, postcode, lat, lon,
       auto_accept, collection_commission, delivery_order_cutoff_minutes, takeaway_order_cutoff_minutes,
       rest_stale_active_threads_minutes, service_hours_json
FROM public.restaurant_master WHERE rest_ref = 'CRDO';
