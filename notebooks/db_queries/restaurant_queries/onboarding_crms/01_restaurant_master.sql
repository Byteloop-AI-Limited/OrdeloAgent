-- =============================================================================
-- CRMS onboarding · 01 · restaurant_master upsert
-- Idempotent (ON CONFLICT DO UPDATE). On its own it does NOT enable web ordering:
-- that needs CRMS in WEB_ORDERING_ENABLED_REST_REFS (03) and the backend
-- RESTAURANTS registry deployed.
-- =============================================================================
BEGIN;

INSERT INTO public.restaurant_master (
  rest_ref, rest_id, rest_name, rest_email, admins,
  house_number, building_name, street_name, city, postcode, lat, lon,
  rest_stale_active_threads_minutes,
  restaurant_start_time, restaurant_end_time,           -- legacy WhatsApp columns (h.mm floats)
  service_hours_json,                                    -- what the web path actually enforces
  delivery_order_cutoff_minutes, takeaway_order_cutoff_minutes,
  collection_commission, auto_accept
)
VALUES (
  'CRMS',
  '447595246457',
  'Creams Orpington',
  'admin@byteloop.ai',
  ARRAY['447448440754'],          -- TEMPORARY test-phase admin. Replaced in 04_go_live.sql
  'Unit 75 & 77',
  'The Walnuts Shopping Centre',
  'High St.',
  'Orpington',
  'BR6 0TW',
  51.37657021668398,
  0.1010799851892783,
  10,
  11,
  23.59,                          -- legacy column, not read by the web path. 23.59 keeps the 0-24 h.mm convention
  '{
    "mon": [["11:00", "24:00"]],
    "tue": [["11:00", "24:00"]],
    "wed": [["11:00", "24:00"]],
    "thu": [["11:00", "24:00"]],
    "fri": [["11:00", "24:00"]],
    "sat": [["11:00", "24:00"]],
    "sun": [["11:00", "24:00"]]
  }'::jsonb,                      -- 11am to midnight. With the 15-minute cutoff the last web order is 23:45
  15,
  15,
  0.10,                           -- 10% collection commission
  FALSE                           -- manual Accept/Decline by the admins over Ordelo WhatsApp
)
ON CONFLICT (rest_ref) DO UPDATE
SET rest_id                           = EXCLUDED.rest_id,
    rest_name                         = EXCLUDED.rest_name,
    rest_email                        = EXCLUDED.rest_email,
    admins                            = EXCLUDED.admins,
    house_number                      = EXCLUDED.house_number,
    building_name                     = EXCLUDED.building_name,
    street_name                       = EXCLUDED.street_name,
    city                              = EXCLUDED.city,
    postcode                          = EXCLUDED.postcode,
    lat                               = EXCLUDED.lat,
    lon                               = EXCLUDED.lon,
    rest_stale_active_threads_minutes = EXCLUDED.rest_stale_active_threads_minutes,
    restaurant_start_time             = EXCLUDED.restaurant_start_time,
    restaurant_end_time               = EXCLUDED.restaurant_end_time,
    service_hours_json                = EXCLUDED.service_hours_json,
    delivery_order_cutoff_minutes     = EXCLUDED.delivery_order_cutoff_minutes,
    takeaway_order_cutoff_minutes     = EXCLUDED.takeaway_order_cutoff_minutes,
    collection_commission             = EXCLUDED.collection_commission,
    auto_accept                       = EXCLUDED.auto_accept;

-- Verify before COMMIT: expect exactly 1 row with the values above.
SELECT rest_ref, rest_id, rest_name, admins, city, postcode, lat, lon, auto_accept,
       service_hours_json, delivery_order_cutoff_minutes, takeaway_order_cutoff_minutes,
       collection_commission
FROM public.restaurant_master WHERE rest_ref = 'CRMS';

COMMIT;   -- change to ROLLBACK for a dry run
