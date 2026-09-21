select max(dispatch_id) from delivery_dispatch;

-- example summary fields
-- {
--   "order_number": "BNAT-FROD-22",
--   "rest_id": "447919202938",
--   "rest_name": "Burger Nation",
--   "rest_lon": "0.099021",
--   "rest_lat": "51.375083",
--   "rest_address": "261 High St. Orpington BR6 0NW",
--   "town": "Orpington",
--   "customer_id": "447424334783",
--   "customer_name": "Jonathan",
--   "customer_lon": "0.0959769",
--   "customer_lat": "51.3541871",
--   "customer_address": "29 Waring Drive Orpington BR6 6DN",
--   "restaurant_confirmation_status": "auto_accept",
--   "restaurant_update_dtts": "2026-08-29 15:00:00+00",
--   "restaurant_admin": null,
--   "status": "completed",
--   "rest_confirmation_code": 33,
--   "cust_confirmation_code": 84,
--   "rest_prep_time_minutes": 30,
--   "rest_confirmation_method": "configured_auto",
--   "restaurant_msg_id": null,
--   "rider_msg_id": null,
--   "customer_msg_id": null,
--   "pickup_time": "2026-08-29 15:30:00+00",
--   "pickup_date": "2026-08-29",
--   "rest_ref": "BNAT",
--   "dt": "2026-08-29",
--   "dtts": "2026-08-29 15:00:00+00",
--   "redispatch_dtts": null
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
      'BNAT-JSLI-27'::varchar AS order_number,
      rider_id,
      6.55::double precision AS rider_payout,
      vehicle_type,
      1.45::double precision AS distance,
      row_num
    FROM rider_rows
  ),
  summary_data AS (
    SELECT
    -- current time + 30 mins; timestamptz carries the live UTC offset,
    -- so BST/GMT clock changes need no manual adjustment
      (now() + interval '30 minutes') AS pickup_time,
      '447919202938'::varchar AS rest_id,
      'Burger Nation'::varchar AS rest_name,
      '0.099021'::varchar AS rest_lon,
      '51.375083'::varchar AS rest_lat,
      '261 High St. Orpington BR6 0NW'::varchar AS rest_address,
      'Orpington'::varchar AS town,
      '447428345882'::varchar AS customer_id,
      'Sujith'::varchar AS customer_name,
      '0.0861972'::varchar AS customer_lon,
      '51.360293'::varchar AS customer_lat,
      '16 Ashley Gardens, Orpington BR6 9NH'::varchar AS customer_address
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

-- SELECT fake_delivery_dispatch_whook();


SELECT fake_delivery_dispatch_whook(
  (
    SELECT array_agg(rider_id ORDER BY rider_name)
    FROM rider_master
    WHERE is_in_shift = true
      AND rider_name IN ('Lohith')
      -- AND rider_name IN ('Leonardo', 'Rehan', 'Rahul', 'Majid', 'Muhammad', 'Lohith')
  )
);

select * from rider_master where is_in_shift = true;
SELECT config_value 
  FROM ordelo_config
 WHERE config_key = 'ORDELO_APP_URL';
