-- Restaurant master INSERT prepared for manual execution. Not executed by the agent.
-- Source: website_source.json, observed 2026-10-11.
-- Populated from identity: name, email and address components.
-- Populated from hours.food_service_hours_json: daily food service 12:00-21:30.
-- Legacy start/end values use h.mm: 12 and 21.30. Later bar hours do not apply.
-- User confirmed 2026-10-12: coordinates, admin 447448440754,
-- delivery/takeaway cutoffs 15 minutes, collection commission 0.1 (10%),
-- stale active-thread timeout 10 minutes and auto_accept=true.
-- Confirm delivery/collection availability before launch.
-- Proposed rest_ref STRK must pass preflight. Do not overwrite an existing row.
-- Public phone 01689 637 100 is not automatically a WhatsApp rest_id;
-- rest_id stays NULL pending confirmation.
INSERT INTO public.restaurant_master (
  rest_ref,rest_id,rest_name,rest_email,admins,
  house_number,building_name,street_name,city,postcode,lat,lon,
  service_hours_json,delivery_order_cutoff_minutes,takeaway_order_cutoff_minutes,
  collection_commission,auto_accept,rest_stale_active_threads_minutes,
  restaurant_start_time,restaurant_end_time
) VALUES (
  'STRK',NULL,'Strikers Sports Bar','hello@strikersbar.com',
  ARRAY['447448440754'],
  '40b','The Walnuts','High Street','Orpington','BR6 0TW',
  51.37662725472839, 0.10095080530129438,
  '{"mon":[["12:00","21:30"]],"tue":[["12:00","21:30"]],"wed":[["12:00","21:30"]],"thu":[["12:00","21:30"]],"fri":[["12:00","21:30"]],"sat":[["12:00","21:30"]],"sun":[["12:00","21:30"]]}'::jsonb,
  15,15,
  0.1,true,10,
  12,21.30
) RETURNING rest_ref,rest_name,admins,city,postcode,lat,lon,service_hours_json,
            collection_commission,auto_accept;

SELECT rest_ref,rest_name,rest_email,city,postcode,lat,lon,auto_accept,
       service_hours_json,collection_commission
FROM public.restaurant_master WHERE rest_ref='STRK';
