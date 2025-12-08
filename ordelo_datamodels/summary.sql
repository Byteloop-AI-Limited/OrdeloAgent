
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
    status          VARCHAR(50) NOT NULL CHECK (status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline', 'unassigned', 'timedout', 'assigned', 'completed')),
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
-- Trigger 1: On new record with status='restaurant_unconfirmed' OR status update to 'restaurant_accept'/'restaurant_decline'
CREATE OR REPLACE TRIGGER trigger_restaurant_updates 
AFTER INSERT OR UPDATE ON public.delivery_summary 
FOR EACH ROW 
WHEN (NEW.status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline'))
EXECUTE FUNCTION restaurant_updates_whook();

drop trigger trigger_restaurant_updates on delivery_summary;

-- Trigger2: On status change to timeout
drop trigger trigger_delivery_summary_timedout on public.delivery_summary;

CREATE OR REPLACE TRIGGER trigger_delivery_summary_timedout AFTER
UPDATE ON public.delivery_summary
FOR EACH ROW WHEN (OLD.status <> 'timedout'
                   AND NEW.status = 'timedout') EXECUTE FUNCTION public.delivery_summary_timedout_whook();



-- Trigger Functions
/** description: restaurant_updates_whook
 *  purpose: Sends a webhook request to the Ordelo app for restaurant updates workflow events
 *  parameters: 
 *    - NEW: The new/updated delivery_summary record
 *    - OLD: The old delivery_summary record (for UPDATE operations)
 *  returns: 
 *    - TRIGGER: The trigger object
 *  notes:
 *    - Triggered on delivery_summary INSERT with status='restaurant_unconfirmed'
 *    - Triggered on delivery_summary UPDATE to status='restaurant_accept' or 'restaurant_decline'
 *    - Builds delivery_summary JSON from NEW record (all fields)
 *    - Fetches restaurant_master data and includes in payload
 *    - Joins with food_order table using order_number
 *    - Fetches order items from order_item table
 *    - Includes trigger_reason field indicating the status that triggered the webhook
 *    - Constructs JSON matching RestaurantConfirmationPayload model (DeliverySummaryData + RestaurantMaster + FoodOrder + List[OrderItem])
 */
CREATE OR REPLACE FUNCTION restaurant_updates_whook()
RETURNS TRIGGER AS $$
DECLARE
  webhook_payload json;
  ordelo_app_url text;
  webhook_url text;
  response json;
  delivery_summary_json json;
  restaurant_master_json json;
  food_order_json json;
  order_items_json json;
  food_order_id text;
  trigger_reason text;
  p_log_to_table BOOLEAN := TRUE; -- Default to TRUE, can be controlled via config
BEGIN
  -- Check if logging is enabled (can be disabled via ordelo_config table)
  BEGIN
    SELECT COALESCE((config_value::BOOLEAN), TRUE) INTO p_log_to_table
    FROM ordelo_config 
    WHERE config_key = 'ENABLE_TRIGGER_DEBUG_LOG';
  EXCEPTION
    WHEN OTHERS THEN
      p_log_to_table := TRUE; -- Default to TRUE if config not found
  END;

  -- Determine trigger reason
  trigger_reason := NEW.status;
  
  -- Log trigger fired
  IF p_log_to_table THEN
    INSERT INTO debug_log (trigger_name, order_number, message)
    VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Trigger fired, trigger_reason: ' || trigger_reason || ', TG_OP: ' || TG_OP);
  END IF;

  -- Process for restaurant_unconfirmed, restaurant_accept, or restaurant_decline
  IF NEW.status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline') THEN
    
    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message)
      VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Status check passed - ' || NEW.status);
    END IF;
    
    -- Build delivery_summary JSON from NEW record
    SELECT json_build_object(
      'order_number', NEW.order_number,
      'rest_id', NEW.rest_id,
      'rest_name', NEW.rest_name,
      'rest_lon', NEW.rest_lon,
      'rest_lat', NEW.rest_lat,
      'rest_address', NEW.rest_address,
      'town', NEW.town,
      'customer_id', NEW.customer_id,
      'customer_name', NEW.customer_name,
      'customer_lon', NEW.customer_lon,
      'customer_lat', NEW.customer_lat,
      'customer_address', NEW.customer_address,
      'status', NEW.status,
      'rest_confirmation_code', NEW.rest_confirmation_code,
      'cust_confirmation_code', NEW.cust_confirmation_code,
      'rest_confirmed_at', NEW.rest_confirmed_at,
      'rest_prep_time_minutes', NEW.rest_prep_time_minutes,
      'rest_confirmation_method', NEW.rest_confirmation_method,
      'pickup_time', NEW.pickup_time,
      'pickup_date', NEW.pickup_date,
      'dt', NEW.dt,
      'dtts', NEW.dtts
    ) INTO delivery_summary_json;
    
    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message)
      VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Delivery summary JSON built');
    END IF;
    
    -- Fetch restaurant_master data by rest_id and build JSON
    SELECT json_build_object(
      'rest_id', rm.rest_id,
      'rest_ref', rm.rest_ref,
      'rest_name', rm.rest_name,
      'admins', rm.admins,
      'lon', rm.lon,
      'lat', rm.lat,
      'house_number', rm.house_number,
      'building_name', rm.building_name,
      'street_name', rm.street_name,
      'city', rm.city,
      'postcode', rm.postcode
    )
    INTO restaurant_master_json
    FROM restaurant_master rm
    WHERE rm.rest_id = NEW.rest_id;
    
    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message)
      VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Restaurant master data fetched for rest_id: ' || NEW.rest_id);
    END IF;
    
    -- Fetch food_order data by order_number and build JSON
    SELECT 
      json_build_object(
        'order_id', fo.order_id,
        'order_number', fo.order_number,
        'seq_id', fo.seq_id,
        'recipient', fo.recipient,
        'thread_id', fo.thread_id,
        'action', fo.action,
        'total_price', fo.total_price,
        'final_order_value', fo.final_order_value,
        'rest_cost', fo.rest_cost,
        'service_charge', fo.service_charge,
        'delivery_fee', fo.delivery_fee,
        'small_order_fee', fo.small_order_fee,
        'commission_rate', fo.commission_rate,
        'payment_status', fo.payment_status
      ),
      fo.order_id
    INTO food_order_json, food_order_id
    FROM food_order fo
    WHERE fo.order_number = NEW.order_number;
    
    -- Check if food_order was found
    IF food_order_json IS NULL THEN
      IF p_log_to_table THEN
        INSERT INTO debug_log (trigger_name, order_number, message)
        VALUES ('restaurant_confirmation_whook', NEW.order_number, 'WARNING: No food_order found for order_number');
      END IF;
      RAISE WARNING 'No food_order found for order_number %', NEW.order_number;
      RETURN NEW;
    END IF;
    
    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message)
      VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Food order found: ' || food_order_id);
    END IF;
    
    -- Fetch order items for this order
    SELECT json_agg(
      json_build_object(
        'order_id', oi.order_id,
        'sku', oi.sku,
        'quantity', oi.quantity,
        'price', oi.price,
        'product_name', oi.product_name
      )
    )
    INTO order_items_json
    FROM order_item oi
    WHERE oi.order_id = food_order_id;
    
    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message)
      VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Order items fetched, count: ' || COALESCE(json_array_length(order_items_json), 0));
    END IF;
    
    -- Build complete webhook payload with all components
    SELECT json_build_object(
      'trigger_reason', trigger_reason,
      'delivery_summary', delivery_summary_json,
      'restaurant_master', restaurant_master_json,
      'food_order', food_order_json,
      'order_items', COALESCE(order_items_json, '[]'::json)
    ) INTO webhook_payload;
    
    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message, payload)
      VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Complete webhook payload built', webhook_payload::jsonb);
    END IF;
    
    -- Get webhook URL from config
    SELECT config_value INTO ordelo_app_url 
    FROM ordelo_config 
    WHERE config_key = 'ORDELO_APP_URL';
    
    IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
      ordelo_app_url := 'https://rider-agent.ordelo.app';
    END IF;
    
    webhook_url := ordelo_app_url || '/delivery-hooks/restaurant-confirmation-request';
    
    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message)
      VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Webhook URL: ' || webhook_url);
    END IF;
    
    -- Make HTTP POST
    response := (
      SELECT content
      FROM http_post(
        webhook_url,
        webhook_payload::text,
        'application/json'
      )
    );
    
    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message, payload)
      VALUES ('restaurant_confirmation_whook', NEW.order_number, 'HTTP response received', response::jsonb);
    END IF;
    
    RAISE NOTICE 'Restaurant confirmation request sent for order %: %', NEW.order_number, response;
  ELSE
    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message)
      VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Status check failed, current status: ' || NEW.status);
    END IF;
  END IF;
  
  RETURN NEW;
EXCEPTION
  WHEN OTHERS THEN
    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message)
      VALUES ('restaurant_confirmation_whook', NEW.order_number, 'ERROR: ' || SQLERRM);
    END IF;
    RAISE WARNING 'Error in restaurant_confirmation_whook for order %: %', NEW.order_number, SQLERRM;
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
