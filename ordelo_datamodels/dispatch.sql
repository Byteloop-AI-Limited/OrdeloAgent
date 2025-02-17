CREATE TABLE delivery_dispatch (
    dispatch_id      SERIAL PRIMARY KEY,
    order_number     VARCHAR(100) NOT NULL,
    rider_id        VARCHAR(12) NOT NULL,
    rider_payout    DOUBLE PRECISION NOT NULL,
    distance         DOUBLE PRECISION NOT NULL,
    status          VARCHAR(50) NOT NULL CHECK (status IN ('unassigned', 'assigned', 'completed', 'declined')),
    status_update_dtts             TIMESTAMP,
    dt               DATE NOT NULL DEFAULT CURRENT_DATE,
    ddts             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

------------------------------------------------
-- Trigger 
------------------------------------------------
CREATE OR REPLACE FUNCTION public.delivery_dispatch_whook()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  response json;
  webhook_payload json;
BEGIN
  -- Combine the NEW record with additional data from a SELECT query
  SELECT json_build_object(
    'delivery_dispatch', json_build_array(row_to_json(NEW)),
    'delivery_detail', (
      -- Replace this SELECT with your actual query
      SELECT json_agg(row_to_json(t))
      FROM (
        SELECT * FROM delivery_detail 
        WHERE order_number=NEW.order_number
        LIMIT 1
      ) t
    )
  ) INTO webhook_payload;

  -- Make the HTTP POST request with the combined payload
  response := (
    SELECT content 
    FROM http_post(
      'https://live-track.byteloop.ai/delivery-hooks/delivery-dispatch', 
      webhook_payload::text,
      'application/json'
    )
  );

  -- Log the response
  RAISE NOTICE 'Response from HTTP POST: %', response;

  RETURN NEW;
END;
$$;

-- Trigger to call the webhook
CREATE TRIGGER trigger_delivery_dispatch_whook
AFTER INSERT ON public.delivery_dispatch
FOR EACH ROW
EXECUTE FUNCTION public.delivery_dispatch_whook();

-- cleanup
drop trigger if exists trigger_delivery_dispatch_whook on delivery_dispatch;
drop table delivery_dispatch;