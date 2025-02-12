--  %% Have to enale http database extension on Public

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
      'https://live-track.byteloop.ai/delivery-hooks/delivery_dispatch', 
      webhook_payload::text,
      'application/json'
    )
  );

  -- Log the response
  RAISE NOTICE 'Response from HTTP POST: %', response;

  RETURN NEW;
END;
$$;

CREATE TRIGGER trigger_delivery_dispatch_whook
AFTER INSERT ON public.delivery_dispatch
FOR EACH ROW
EXECUTE FUNCTION public.delivery_dispatch_whook();

-- Trigger for delivery_detail

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
    'delivery_detail', json_build_array(row_to_json(NEW)),
    'delivery_dispatch', (
      -- Replace this SELECT with your actual query
      SELECT json_agg(row_to_json(t))
      FROM (
        SELECT * FROM delivery_dispatch 
        WHERE order_number=NEW.order_number AND status='accepted'
        LIMIT 1
      ) t
    )
  ) INTO webhook_payload;

  -- Make the HTTP POST request with the combined payload
  response := (
    SELECT content 
    FROM http_post(
      'https://live-track.byteloop.ai/delivery-hooks/delivery_detail_update', 
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
EXECUTE FUNCTION public.delivery_detail_update_whook();