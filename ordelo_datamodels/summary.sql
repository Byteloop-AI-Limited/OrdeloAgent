-- drop table delivery_summary;
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
    -- Restaurant confirmation status (separate from delivery lifecycle)
    restaurant_confirmation_status VARCHAR(50) NOT NULL DEFAULT 'restaurant_unconfirmed' 
        CHECK (restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline', 'restaurant_timedout', 'auto_accept','auto_decline','restaurant_pickuptime_adjusted')),
    restaurant_update_dtts TIMESTAMP WITH TIME ZONE, -- nullable, set when restaurant_confirmation_status changes
    restaurant_admin VARCHAR(12), -- nullable, stores the admin phone who confirmed the order
    -- Delivery lifecycle status
    status          VARCHAR(50) NOT NULL CHECK (status IN ('restaurant_unconfirmed', 'unassigned', 'timedout', 'assigned', 'completed')),
    rest_confirmation_code INTEGER NOT NULL,
    cust_confirmation_code INTEGER NOT NULL,
    rest_prep_time_minutes INTEGER,
    rest_confirmation_method VARCHAR(20),
    -- WhatsApp message IDs for tracking communications
    restaurant_msg_id VARCHAR(255), -- nullable, stores WA message ID for restaurant communications
    rider_msg_id VARCHAR(255), -- nullable, stores WA message ID for rider communications
    customer_msg_id VARCHAR(255), -- nullable, stores WA message ID for customer communications
    -- Scheduled pickup time selected by restaurant admins via `/PickupTime` callback.
    -- Downstream:
    -- 1) Included in webhook payload from restaurant_updates_whook()
    -- 2) Included later in rider dispatch payload/message
    -- 3) If NULL past timeout, process_restaurant_confirmation() moves flow to restaurant_timedout
    pickup_time      TIMESTAMP WITH TIME ZONE,
    pickup_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    rest_ref         VARCHAR(20) GENERATED ALWAYS AS (SPLIT_PART(order_number, '-', 1)) STORED, -- derived from order_number
    dt               DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- "Current dispatch window started at" — populated only by
    -- dispatch_cancel_before_pickup on a successful pre-pickup decline.
    -- process_delivery uses COALESCE(redispatch_dtts, dtts) for the timeout
    -- base, so NULL means "no decline yet, use dtts".
    redispatch_dtts  TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (order_number)
);
-- drop table delivery_summary;

-- Triggers on delivery_summary table
-- Trigger 1: On new record OR restaurant_confirmation_status update to 'restaurant_accept'/'restaurant_decline'/'restaurant_timedout'
-- This is the entry point for the restaurant-confirmation webhook chain:
-- delivery_summary change -> trigger_restaurant_updates -> restaurant_updates_whook()
-- -> POST /delivery-hooks/restaurant-confirmation-request -> restaurant_confirmation_flow()
-- -> _handle_restaurant_accept() when trigger_reason='restaurant_accept' (pickup-time options are sent)
CREATE OR REPLACE TRIGGER trigger_restaurant_updates 
AFTER INSERT OR UPDATE OF restaurant_confirmation_status ON public.delivery_summary 
FOR EACH ROW 
WHEN (NEW.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline', 'restaurant_timedout', 'restaurant_pickuptime_adjusted'))
EXECUTE FUNCTION restaurant_updates_whook();

-- drop trigger trigger_restaurant_updates on delivery_summary;

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
 *    - Triggered on delivery_summary INSERT with restaurant_confirmation_status='restaurant_unconfirmed'
 *    - Triggered on delivery_summary UPDATE to restaurant_confirmation_status='restaurant_accept', 'restaurant_decline', 'restaurant_timedout', or 'restaurant_pickuptime_adjusted'
 *    - For trigger_reason='restaurant_accept', API handler _handle_restaurant_accept() sends pickup-time buttons
 *      and the selected value is written back to delivery_summary.pickup_time via /PickupTime callback
 *    - For trigger_reason='restaurant_timedout', API handler _handle_restaurant_timedout() auto-sets pickup_time (+30 mins)
 *    - For trigger_reason='restaurant_pickuptime_adjusted', set when an admin adjusts an already-set pickup_time
 *      (via /AdminAdjustPickupTime callback); API handler _handle_restaurant_pickuptime_adjusted() notifies the inflight rider
 *    - Builds delivery_summary JSON from NEW record (all fields)
 *    - Fetches restaurant_master data and includes in payload
 *    - Joins with food_order table using order_number
 *    - Fetches order items from order_item table
 *    - Includes trigger_reason field indicating the restaurant_confirmation_status that triggered the webhook
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
  PERFORM set_config('statement_timeout', '10000', true);
  -- Check if logging is enabled (can be disabled via ordelo_config table)
  BEGIN
    SELECT COALESCE((config_value::BOOLEAN), TRUE) INTO p_log_to_table
    FROM ordelo_config 
    WHERE config_key = 'ENABLE_TRIGGER_DEBUG_LOG';
  EXCEPTION
    WHEN OTHERS THEN
      p_log_to_table := TRUE; -- Default to TRUE if config not found
  END;

  -- Determine trigger reason from restaurant_confirmation_status
  trigger_reason := NEW.restaurant_confirmation_status;
  
  -- Log trigger fired
  IF p_log_to_table THEN
    INSERT INTO debug_log (trigger_name, order_number, message)
    VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Trigger fired, trigger_reason: ' || trigger_reason || ', TG_OP: ' || TG_OP);
  END IF;

  -- Process for restaurant_unconfirmed, restaurant_accept, restaurant_decline, or restaurant_timedout
  IF NEW.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline', 'restaurant_timedout', 'restaurant_pickuptime_adjusted') THEN
    
    IF p_log_to_table THEN
      INSERT INTO debug_log (trigger_name, order_number, message)
      VALUES ('restaurant_confirmation_whook', NEW.order_number, 'restaurant_confirmation_status check passed - ' || NEW.restaurant_confirmation_status);
    END IF;
    
    -- Build delivery_summary JSON from NEW record (includes new columns)
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
      'restaurant_confirmation_status', NEW.restaurant_confirmation_status,
      'restaurant_update_dtts', NEW.restaurant_update_dtts,
      'restaurant_admin', NEW.restaurant_admin,
      'status', NEW.status,
      'rest_confirmation_code', NEW.rest_confirmation_code,
      'cust_confirmation_code', NEW.cust_confirmation_code,
      'rest_prep_time_minutes', NEW.rest_prep_time_minutes,
      'rest_confirmation_method', NEW.rest_confirmation_method,
      'restaurant_msg_id', NEW.restaurant_msg_id,
      'rider_msg_id', NEW.rider_msg_id,
      'customer_msg_id', NEW.customer_msg_id,
      'pickup_time', NEW.pickup_time,
      'pickup_date', NEW.pickup_date,
      'rest_ref', NEW.rest_ref,
      'dt', NEW.dt,
      'dtts', NEW.dtts,
      'redispatch_dtts', NEW.redispatch_dtts
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
      VALUES ('restaurant_confirmation_whook', NEW.order_number, 'restaurant_confirmation_status check failed, current: ' || NEW.restaurant_confirmation_status);
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
  PERFORM set_config('statement_timeout', '10000', true);
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


-- Set timeout for 30s
ALTER DATABASE postgres SET statement_timeout = '300s';
