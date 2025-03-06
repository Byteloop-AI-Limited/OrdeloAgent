CREATE TABLE delivery_inflight (
    dispatch_id     INTEGER,
    order_number     VARCHAR(100) NOT NULL,
    rider_id        VARCHAR(12) NOT NULL,
    customer_id        VARCHAR(12) NOT NULL,
    dt               DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (dispatch_id)
);

-- Webhook function for delivery_inflight
CREATE OR REPLACE FUNCTION public.delivery_inflight_whook()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  response json;
  webhook_payload json;
  notify_result BOOLEAN;
BEGIN
  -- Combine the NEW record with additional data from delivery_detail
  SELECT json_build_object(
    'delivery_inflight', json_build_array(row_to_json(NEW)),
    'delivery_detail', (
      SELECT json_agg(row_to_json(t))
      FROM (
        SELECT * FROM delivery_detail 
        WHERE order_number = NEW.order_number AND dispatch_id = NEW.dispatch_id
        LIMIT 1
      ) t
    )
  ) INTO webhook_payload;

  -- Make the HTTP POST request with the combined payload
  response := (
    SELECT content 
    FROM http_post(
      'https://agent.ordelo.app/delivery-hooks/delivery-inflight-graph-init', 
      webhook_payload::text,
      'application/json'
    )
  );
  
  -- Log the response
  RAISE NOTICE 'Response from HTTP POST to delivery-inflight-graph-init: %', response;
  
  -- Call notify_missed_dispatches_for_order with the order number
  SELECT notify_missed_dispatches_for_order(NEW.order_number) INTO notify_result;
  
  -- Log the result of notify_missed_dispatches_for_order
  RAISE NOTICE 'Result of notify_missed_dispatches_for_order for order %: %', NEW.order_number, notify_result;
  
  RETURN NEW;
END;
$$;

-- Trigger to call the webhook
CREATE TRIGGER trigger_delivery_inflight_whook
AFTER INSERT ON public.delivery_inflight
FOR EACH ROW
EXECUTE FUNCTION public.delivery_inflight_whook();
