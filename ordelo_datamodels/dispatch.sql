/**
Dispatch Creation and Management Process

Invocation:
1. Trigger when a dispatch is inserted into deliver_dispatch
2. Function call: create_dispatch()

Purpose:
- Manage unassigned orders
- Create new dispatch entries
- Update delivery_detail with timeout status

Execution:
- Frequency: Trigger based

Side Effects:
1. Trigger webhook: /delivery-hooks/delivery-dispatch on insert
2. Send WhatsApp messages to riders with delivery summaries
**/

CREATE TABLE delivery_dispatch (
    dispatch_id     SERIAL PRIMARY KEY,
    order_number    VARCHAR(100) NOT NULL,
    rider_id        VARCHAR(12) NOT NULL,
    rider_payout    DOUBLE PRECISION NOT NULL,
    vehicle_type    VARCHAR(15) NOT NULL,
    distance        DOUBLE PRECISION NOT NULL,
    status          VARCHAR(50) NOT NULL CHECK (status IN ('unassigned', 'timedout', 'declined', 'accepted', 'missed', 'assigned', 'completed')),
    status_update_dtts TIMESTAMP,
    dt               DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

------------------------------------------------
-- 
------------------------------------------------
CREATE OR REPLACE FUNCTION public.delivery_dispatch_whook()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  response json;
  webhook_payload json;
BEGIN
  -- Build webhook payload combining the new dispatch and rich delivery detail
  SELECT json_build_object(
    'delivery_dispatch', json_build_array(row_to_json(NEW)),
    'delivery_detail', (
      SELECT json_agg(row_to_json(t))
      FROM (
        SELECT 
          det.order_number, 
          det.vehicle_type, 
          det.rider_payout,
          det.distance, 
          det.rest_id, 
          det.rest_name, 
          det.rest_lon, 
          det.rest_lat, 
          det.rest_address, 
          det.town, 
          det.customer_id, 
          summ.customer_name, 
          summ.customer_lon, 
          summ.customer_lat, 
          summ.customer_address, 
          det.status, 
          det.dispatch_id, 
          det.rider_id
        FROM delivery_detail det
        INNER JOIN delivery_summary summ ON det.order_number = summ.order_number
        WHERE det.order_number = NEW.order_number
        ORDER BY det.dtts DESC
        LIMIT 1
      ) t
    )
  ) INTO webhook_payload;

  -- Make the HTTP POST request with the combined payload
  response := (
    SELECT content 
    FROM http_post(
      'https://agent.ordelo.app/delivery-hooks/delivery-dispatch', 
      webhook_payload::text,
      'application/json'
    )
  );
  -- Log the response
  RAISE NOTICE 'Response from HTTP POST: %', response;
  RETURN NEW;
END;
$$;

-- Trigger to call the webhook on row insert
DROP TRIGGER IF EXISTS trigger_delivery_dispatch_whook ON public.delivery_dispatch;

CREATE TRIGGER trigger_delivery_dispatch_whook
AFTER INSERT ON public.delivery_dispatch
FOR EACH ROW
EXECUTE FUNCTION public.delivery_dispatch_whook();


-- bulk
select 
new_rows.dispatch_id,
new_rows.order_number,
new_rows.rider_id,
new_rows.rider_payout,
new_rows.vehicle_type,
new_rows.distance
from delivery_dispatch new_rows 
join delivery_detail det on new_rows.order_number = det.order_number and det.vehicle_type = new_rows.vehicle_type