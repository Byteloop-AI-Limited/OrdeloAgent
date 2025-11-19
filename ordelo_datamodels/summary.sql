
CREATE TABLE delivery_summary (
    order_number     VARCHAR(100),
    rest_id          VARCHAR(12) NOT NULL, -- restaurant id
    rest_name        TEXT NOT NULL,
    rest_lon         DOUBLE PRECISION NOT NULL,
    rest_lat         DOUBLE PRECISION NOT NULL,
    rest_address     TEXT NOT NULL,
    town        VARCHAR(255) NOT NULL,
    customer_id          VARCHAR(50) NOT NULL, -- customer id
    customer_name        TEXT NOT NULL,
    customer_lon         DOUBLE PRECISION NOT NULL,
    customer_lat         DOUBLE PRECISION NOT NULL,
    customer_address     TEXT NOT NULL,
    status          VARCHAR(50) NOT NULL CHECK (status IN ('unassigned', 'timedout', 'assigned', 'completed')),
    rest_confirmation_code INTEGER NOT NULL,
    cust_confirmation_code INTEGER NOT NULL,
    rest_confirmed_at TIMESTAMP WITH TIME ZONE,
    rest_prep_time_minutes INTEGER,
    rest_confirmation_method VARCHAR(20),
    pickup_time      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP + INTERVAL '30 minutes',
    pickup_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    dt               DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (order_number)
);
-- drop table delivery_summary;

-- Triggers on delivery_summary table
-- Trigger 1: On new record with status='restaurant_unconfirmed'
CREATE OR REPLACE TRIGGER trigger_restaurant_confirmation_request AFTER 
INSERT ON delivery_summary FOR EACH ROW
WHEN (NEW.status = 'restaurant_unconfirmed')
EXECUTE FUNCTION restaurant_confirmation_whook();

-- Trigger2: On status change to timeout

CREATE OR REPLACE TRIGGER trigger_delivery_summary_timedout AFTER
UPDATE ON public.delivery_summary
FOR EACH ROW WHEN (OLD.status <> 'timedout'
                   AND NEW.status = 'timedout') EXECUTE FUNCTION public.delivery_summary_timedout_whook();



-- Trigger Functions
/** description: restaurant_confirmation_whook
 *  purpose: Sends a webhook request to the Ordelo app when a new order is created with status 'restaurant_unconfirmed'
 *  parameters: 
 *    - NEW: The new record being inserted
 *  returns: 
 *    - TRIGGER: The trigger object
 */
CREATE OR REPLACE FUNCTION restaurant_confirmation_whook()
RETURNS TRIGGER AS $$
DECLARE
  webhook_payload json;
  ordelo_app_url text;
  webhook_url text;
  response json;
BEGIN
  -- Only trigger for new restaurant_unconfirmed orders
  IF NEW.status = 'restaurant_unconfirmed' THEN
    
    -- Build payload
    SELECT json_build_object(
      'order_number', NEW.order_number,
      'rest_id', NEW.rest_id,
      'rest_name', NEW.rest_name,
      'order_time', NEW.dtts
    ) INTO webhook_payload;
    
    -- Get webhook URL from config
    SELECT config_value INTO ordelo_app_url 
    FROM ordelo_config 
    WHERE config_key = 'ORDELO_APP_URL';
    
    IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
      ordelo_app_url := 'https://rider-agent.ordelo.app';
    END IF;
    
    webhook_url := ordelo_app_url || '/delivery-hooks/restaurant-confirmation-request';
    
    -- Make HTTP POST
    response := (
      SELECT content
      FROM http_post(
        webhook_url,
        webhook_payload::text,
        'application/json'
      )
    );
    
    RAISE NOTICE 'Restaurant confirmation request sent for order %: %', NEW.order_number, response;
  END IF;
  
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger 2:
/*
Delivery Summary Timedout Webhook Trigger
  . Fetches the base app URL from ordelo_config (key: ORDELO_APP_URL)
  . Constructs the webhook URL by appending '/delivery-hooks/delivery-timedout'
  . Constructs JSON payload from NEW record
  . Makes HTTP POST to the constructed webhook URL
  . Logs the response
  . Returns NEW for trigger continuation
Functions:
  . delivery_summary_timedout_whook
*/
CREATE OR REPLACE FUNCTION public.delivery_summary_timedout_whook() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  response json;
  webhook_payload json;
  ordelo_app_url text;
  webhook_url text;
BEGIN
  -- Combine the NEW record with additional data from delivery_detail; required to invoke graph
  SELECT json_build_object(
    'delivery_summary', json_build_array(row_to_json(NEW))
  ) INTO webhook_payload;

  -- Fetch the base app URL from config, fallback to default if not present
  SELECT config_value INTO ordelo_app_url FROM ordelo_config WHERE config_key = 'ORDELO_APP_URL';
  IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
    ordelo_app_url := 'https://rider-agent.ordelo.app';
  END IF;
  webhook_url := ordelo_app_url || '/delivery-hooks/delivery-timedout';

  -- Make the HTTP POST request with the combined payload
  response := (
    SELECT content
    FROM http_post(
      webhook_url,
      webhook_payload::text,
      'application/json'
    )
  );

  -- Log the response
  RAISE NOTICE 'Response from HTTP POST to delivery-timedout: %', response;

  RETURN NEW;
END;
$$;
