select max(dispatch_id) from delivery_dispatch;

select pickup_time, rest_id, rest_name, rest_lon, rest_lat, rest_address, town, customer_id, customer_name, customer_lon, customer_lat, customer_address 
from delivery_summary where order_number = 'SFCS-CJSR-23';

-- example summary fields
-- {
--   "pickup_time": "2026-05-30 16:56:18.290137+00", -- now() + 20 mins
--   "rest_id": "447448441234",
--   "rest_name": "Southern Fried Chicken",
--   "rest_lon": "-1.79609677126815",
--   "rest_lat": "51.0717612607721",
--   "rest_address": "66 Castle Street Salisbury SP1 3TS",
--   "town": "Salisbury",
--   "customer_id": "447832488101",
--   "customer_name": "447832488101",
--   "customer_lon": "-1.816302",
--   "customer_lat": "51.0787815",
--   "customer_address": "44 Harper Road Salisbury SP2 7HQ"
--  }
--  Example new_rows fields
--  {
--   "dispatch_id": 123456789,
--   "order_number": "SFCS-CJSR-23",
--   "rider_id": "447448440754",
--   "rider_payout": 6.87,
--   "vehicle_type": "car",
--   "distance": 1.5
--  }

CREATE OR REPLACE FUNCTION public.fake_delivery_dispatch_whook(
  p_rider_ids varchar[] DEFAULT ARRAY['447448440754', '447448440754']::varchar[]
) RETURNS json AS $$
DECLARE
  response json;
  webhook_payload json;
  app_url varchar;
  hook_url varchar;
BEGIN
  PERFORM set_config('statement_timeout', '10000', true);

  WITH requested_rider_ids AS (
    SELECT rider_id, ordinality::int AS row_num
    FROM unnest(p_rider_ids) WITH ORDINALITY AS r(rider_id, ordinality)
  ),
  rider_rows AS (
    SELECT
      requested_rider_ids.row_num,
      rm.rider_id,
      rm.vehicle_type
    FROM requested_rider_ids
    JOIN rider_master rm
      ON rm.rider_id = requested_rider_ids.rider_id
    WHERE rm.is_in_shift = true
      AND rm.rider_id = ANY(p_rider_ids)
  ),
  new_rows AS (
    SELECT
      123456789 + row_num AS dispatch_id,
      'SFCS-CJSR-43'::varchar AS order_number,
      rider_id,
      6.87::double precision AS rider_payout,
      vehicle_type,
      1.53::double precision AS distance,
      row_num
    FROM rider_rows
  ),
  summary_data AS (
    SELECT
      now() + interval '20 minutes' AS pickup_time,
      '447448441234'::varchar AS rest_id,
      'Southern Fried Chicken'::varchar AS rest_name,
      '-1.79609677126815'::varchar AS rest_lon,
      '51.0717612607721'::varchar AS rest_lat,
      '66 Castle Street Salisbury SP1 3TS'::varchar AS rest_address,
      'Salisbury'::varchar AS town,
      '447832488101'::varchar AS customer_id,
      '447832488101'::varchar AS customer_name,
      '-1.816302'::varchar AS customer_lon,
      '51.0787815'::varchar AS customer_lat,
      '44 Harper Road Salisbury SP2 7HQ'::varchar AS customer_address
  )
  SELECT json_build_object(
    'bulk_dispatch', COALESCE(json_agg(row_to_json(payload_row) ORDER BY src.row_num), '[]'::json)
  )
  INTO webhook_payload
  FROM (
    SELECT
      rr.row_num,
      nr.dispatch_id,
      nr.order_number,
      nr.rider_id,
      nr.rider_payout,
      nr.vehicle_type,
      nr.distance,
      summ.pickup_time,
      summ.rest_id,
      summ.rest_name,
      summ.rest_lon,
      summ.rest_lat,
      summ.rest_address,
      summ.town,
      summ.customer_id,
      summ.customer_name,
      summ.customer_lon,
      summ.customer_lat,
      summ.customer_address
    FROM rider_rows rr
    LEFT JOIN new_rows nr ON nr.row_num = rr.row_num
    LEFT JOIN summary_data summ ON true
  ) src
  CROSS JOIN LATERAL (
    SELECT
      src.dispatch_id,
      src.order_number,
      src.rider_id,
      src.rider_payout,
      src.vehicle_type,
      src.distance,
      src.pickup_time,
      src.rest_id,
      src.rest_name,
      src.rest_lon,
      src.rest_lat,
      src.rest_address,
      src.town,
      src.customer_id,
      src.customer_name,
      src.customer_lon,
      src.customer_lat,
      src.customer_address
  ) payload_row;

  SELECT config_value INTO app_url
    FROM ordelo_config
   WHERE config_key = 'ORDELO_APP_URL';

  IF app_url IS NULL OR length(app_url) = 0 THEN
    app_url := 'https://rider-agent.ordelo.app';
  END IF;

  IF right(app_url, 1) = '/' THEN
    app_url := left(app_url, length(app_url) - 1);
  END IF;
  hook_url := app_url || '/delivery-hooks/delivery-dispatch';

  response := (
    SELECT content
    FROM http_post(
      hook_url,
      webhook_payload::text,
      'application/json'
    )
  );
  RAISE NOTICE 'Payload sent to %: %', hook_url, webhook_payload;
  RAISE NOTICE 'Response from HTTP POST: %', response;

  RETURN response;
END;
$$ LANGUAGE plpgsql;

SELECT fake_delivery_dispatch_whook();


SELECT fake_delivery_dispatch_whook(
  (
    SELECT array_agg(rider_id ORDER BY rider_name)
    FROM rider_master
    WHERE is_in_shift = true
      AND rider_name IN ('Lohith', 'Mohammed Hoque', 'Nikhil', 'Rahul', 'Marian')
      -- AND rider_name IN ('Lohith', 'Rahul')
  )
);