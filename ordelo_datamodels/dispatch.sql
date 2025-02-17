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
-- Trigger for dispatching delivery requests to rider
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

------------------------------------------------
-- Trigger on dispatch to manage delivery_inflight; 
------------------------------------------------
-- CREATE OR REPLACE FUNCTION public.manage_inflight()
-- RETURNS TRIGGER AS $$
-- BEGIN
--     -- Insert into delivery_inflight when status is 'assigned'
--     IF TG_OP = 'UPDATE' AND NEW.status = 'assigned' THEN
--         INSERT INTO delivery_inflight (dispatch_id, order_number, rider_id, customer_id)
--         SELECT 
--             NEW.dispatch_id,
--             NEW.order_number,
--             NEW.rider_id,
--             dd.customer_id
--         FROM delivery_detail AS dd
--         WHERE dd.order_number = NEW.order_number;
--         RETURN NEW;
--     ELSIF TG_OP = 'UPDATE' AND NEW.status = 'completed' THEN
--         DELETE FROM delivery_inflight WHERE dispatch_id = OLD.dispatch_id;
--         RETURN NEW;
--     END IF;
--     RETURN NULL; -- For other operations, do nothing
-- END;
-- $$ LANGUAGE plpgsql;

-- -- Create a trigger for both insert and update operations
-- CREATE TRIGGER tigger_dispatch_manage_delivery_inflight
-- AFTER UPDATE ON delivery_dispatch
-- FOR EACH ROW
-- EXECUTE FUNCTION public.manage_inflight();

-- cleanup
-- drop trigger if exists tigger_dispatch_manage_delivery_inflight on delivery_dispatch;
-- drop table delivery_dispatch;


------------------------------------------------
-- Trigger on infilght to manage delivery_inflight
------------------------------------------------
CREATE OR REPLACE FUNCTION public.sync_delivery_inflight()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  response json;
  webhook_payload json;
BEGIN
  -- Select all records from delivery_inflight
  SELECT json_build_object(
    'delivery_inflight', (
      SELECT json_agg(row_to_json(t))
      FROM (
        SELECT * FROM delivery_inflight
      ) t
    )
  ) INTO webhook_payload;

  -- Make the HTTP POST request with the payload
  response := (
    SELECT content 
    FROM http_post(
      'https://live-track.byteloop.ai/delivery-hooks/delivery-inflight-sync', 
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
CREATE TRIGGER trigger_sync_delivery_inflight
AFTER INSERT OR UPDATE ON public.delivery_inflight
FOR EACH ROW
EXECUTE FUNCTION public.sync_delivery_inflight();

drop trigger if exists trigger_sync_delivery_inflight on delivery_inflight;