-- MIGRATION (history; do not edit the statements below)
-- Applied to live: pending owner application.
-- Current definitions now live in: ordering/web_order_request.sql
-- Purpose: recover lookup postcodes from locked historical delivery snapshots.
UPDATE public.web_order_request
   SET lookup_postcode = address->>'postcode'
 WHERE lookup_postcode IS NULL
   AND address->>'postcode' ~ '^[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}$';
  

SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'web_order_request'
  AND column_name = 'lookup_postcode';
