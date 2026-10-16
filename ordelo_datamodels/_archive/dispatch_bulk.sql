-- Statement-level trigger for batch dispatch webhooks

-- Drop existing bulk trigger if any
DROP TRIGGER IF EXISTS trigger_delivery_dispatch_whook_bulk ON public.delivery_dispatch;

-- Trigger function to process batch inserts
CREATE OR REPLACE FUNCTION public.delivery_dispatch_whook_statement()
RETURNS trigger AS $$
DECLARE
  response json;
  webhook_payload json;
BEGIN
  -- Build payload by joining new_rows with delivery_detail in one query
  SELECT json_build_object(
    'bulk_dispatch', json_agg(row_to_json(t))
  )
  INTO webhook_payload
  FROM (
    SELECT 
      nr.dispatch_id,
      nr.order_number,
      nr.rider_id,
      nr.rider_payout,
      nr.vehicle_type,
      nr.distance,
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
    FROM new_rows nr 
    JOIN delivery_detail det ON nr.order_number = det.order_number AND det.vehicle_type = nr.vehicle_type
    JOIN delivery_summary summ ON summ.order_number = nr.order_number
  ) t;

  -- Send single HTTP POST for all new rows
  response := (
    SELECT content
    FROM http_post(
      'https://agent.ordelo.app/delivery-hooks/delivery-dispatch-bulk',
      webhook_payload::text,
      'application/json'
    )
  );
  RAISE NOTICE 'Response from HTTP POST: %', response;

  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Statement-level trigger on batch insert
CREATE TRIGGER trigger_delivery_dispatch_whook_bulk
AFTER INSERT ON public.delivery_dispatch
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT
EXECUTE FUNCTION public.delivery_dispatch_whook_statement();
