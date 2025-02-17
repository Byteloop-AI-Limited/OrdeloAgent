CREATE TABLE delivery_detail (
    order_number     VARCHAR(100) PRIMARY KEY,
    rider_payout    DOUBLE PRECISION NOT NULL,
    distance         DOUBLE PRECISION NOT NULL,
    rest_id          VARCHAR(50) NOT NULL, -- restaurant id
    rest_name        TEXT NOT NULL,
    rest_lon         DOUBLE PRECISION NOT NULL,
    rest_lat         DOUBLE PRECISION NOT NULL,
    rest_address     TEXT NOT NULL,
    customer_id          VARCHAR(50) NOT NULL, -- customer id
    customer_name        TEXT NOT NULL,
    customer_lon         DOUBLE PRECISION NOT NULL,
    customer_lat         DOUBLE PRECISION NOT NULL,
    customer_address     TEXT NOT NULL,
    status          VARCHAR(50) NOT NULL CHECK (status IN ('unassigned', 'assigned', 'completed', 'declined')),
    dispatch_id     INTEGER,
    rider_id        VARCHAR(12),
    dt               DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

------------------------------------------------
-- Trigger for delivery_detail
------------------------------------------------
CREATE OR REPLACE FUNCTION public.delivery_detail_update_whook()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  response json;
  webhook_payload json;
BEGIN
  -- Combine the NEW record with additional data from a SELECT query
  SELECT json_build_object(
    'delivery_detail', json_build_array(row_to_json(NEW))
  ) INTO webhook_payload;

  -- Make the HTTP POST request with the combined payload
  response := (
    SELECT content 
    FROM http_post(
      'https://live-track.byteloop.ai/delivery-hooks/delivery-detail-update', 
      webhook_payload::text,
      'application/json'
    )
  );
  -- Log the response
  RAISE NOTICE 'Response from HTTP POST: %', response;
  RETURN NEW;
END;
$$;

CREATE TRIGGER trigger_delivery_detail_whook
AFTER UPDATE OF status ON public.delivery_detail
FOR EACH ROW
WHEN (NEW.status = 'assigned')
EXECUTE FUNCTION public.delivery_detail_update_whook();

-- CLEANUP
-- DROP TRIGGER IF EXISTS trigger_delivery_detail_whook ON delivery_detail;
-- drop table delivery_detail;