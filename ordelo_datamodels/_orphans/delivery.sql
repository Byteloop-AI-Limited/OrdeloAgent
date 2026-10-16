CREATE OR REPLACE FUNCTION insert_delivery_detail(p_cust_id VARCHAR, p_order_number VARCHAR, p_vehicle_type VARCHAR)
RETURNS VOID AS $$
DECLARE
    v_rest_ref VARCHAR;
    v_rider_payout DOUBLE PRECISION;
    v_distance DOUBLE PRECISION;
    v_rest_id VARCHAR(12);
    v_rest_name TEXT;
    v_rest_lon DOUBLE PRECISION;
    v_rest_lat DOUBLE PRECISION;
    v_rest_address TEXT;
    v_town VARCHAR(255);
    v_customer_name TEXT;
    v_customer_lon DOUBLE PRECISION;
    v_customer_lat DOUBLE PRECISION;
    v_customer_address TEXT;
BEGIN
    -- Derive rest_ref from order_number (text before the first '-')
    v_rest_ref := SPLIT_PART(p_order_number, '-', 1);

    -- Fetch delivery option details using the provided vehicle type
    SELECT
        driver_payout,
        (breakdown::JSON ->> 'distance_miles')::DOUBLE PRECISION
    INTO
        v_rider_payout,
        v_distance
    FROM delivery_option
    WHERE vehicle_type = p_vehicle_type 
    AND breakdown IS NOT NULL
    AND order_number = p_order_number
    LIMIT 1; -- Ensure only one row is selected

    -- Raise exception if no delivery option found for the specified type
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Delivery option details not found for vehicle_type: %', p_vehicle_type;
    END IF;

    -- Fetch restaurant details using derived rest_ref
    SELECT
        rm.rest_id,
        rm.rest_name,
        rm.lon,
        rm.lat,
        -- Construct a readable address string
        TRIM(CONCAT_WS(' ', rm.house_number, rm.building_name, rm.street_name, rm.city, rm.postcode)),
        rm.city -- Assuming city maps to town
    INTO
        v_rest_id,
        v_rest_name,
        v_rest_lon,
        v_rest_lat,
        v_rest_address,
        v_town
    FROM restaurant_master rm
    WHERE rm.rest_ref = v_rest_ref;

    -- Raise exception if restaurant not found
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Restaurant details not found for rest_ref: %', v_rest_ref;
    END IF;

    -- Fetch customer details using provided p_cust_id
    SELECT
        cm.cust_name,
        cm.lon,
        cm.lat,
        -- Construct a readable address string
        TRIM(CONCAT_WS(' ', cm.house_number, cm.building_name, cm.street_name, cm.city, cm.postcode))
    INTO
        v_customer_name,
        v_customer_lon,
        v_customer_lat,
        v_customer_address
    FROM customer_master cm
    WHERE cm.cust_id = p_cust_id;

    -- Raise exception if customer not found
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Customer details not found for cust_id: %', p_cust_id;
    END IF;

    -- Insert the collected data into delivery_detail table
    INSERT INTO delivery_detail (
        order_number,
        vehicle_type,
        rider_payout,
        distance,
        rest_id,
        rest_name,
        rest_lon,
        rest_lat,
        rest_address,
        town,
        customer_id,
        customer_name,
        customer_lon,
        customer_lat,
        customer_address,
        status, -- Default status
        dispatch_id, -- Initially NULL
        rider_id     -- Initially NULL
    ) VALUES (
        p_order_number,
        p_vehicle_type,
        v_rider_payout,
        v_distance,
        v_rest_id,
        v_rest_name,
        v_rest_lon,
        v_rest_lat,
        v_rest_address,
        v_town,
        p_cust_id, -- Use the input parameter
        v_customer_name,
        v_customer_lon,
        v_customer_lat,
        v_customer_address,
        'unassigned', -- Default status
        NULL,
        NULL
    );

END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS public.delivery_detail_bkp (
    order_number character varying(100) NOT NULL,
    vehicle_type character varying(15) NOT NULL DEFAULT 'car'::character varying,
    rider_payout double precision NOT NULL,
    distance double precision NOT NULL,
    rest_id character varying(12) NOT NULL,
    rest_name text NOT NULL,
    rest_lon double precision NOT NULL,
    rest_lat double precision NOT NULL,
    rest_address text NOT NULL,
    town character varying(255) NOT NULL,
    customer_id character varying(50) NOT NULL,
    customer_name text NOT NULL,
    customer_lon double precision NOT NULL,
    customer_lat double precision NOT NULL,
    customer_address text NOT NULL,
    status character varying(50) NOT NULL,
    dispatch_id integer,
    rider_id character varying(12),
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT delivery_detail_pkey PRIMARY KEY (order_number, vehicle_type),
    CONSTRAINT delivery_detail_status_check CHECK (((status)::text = ANY ((ARRAY['unassigned'::character varying, 'declined'::character varying, 'timedout'::character varying, 'assigned'::character varying, 'completed'::character varying, 'vehicle_type_timedout'::character varying])::text[])))
);

-- Definition taken from the live database on 2026-10-16 (no repo copy existed).
CREATE OR REPLACE FUNCTION public.delivery_detail_update_whook()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
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
$function$;

-- Definition taken from the live database on 2026-10-16 (no repo copy existed).
CREATE OR REPLACE FUNCTION public.manage_delivery_detail()
 RETURNS text
 LANGUAGE plpgsql
AS $function$
DECLARE
    rec RECORD;
    inserted_details TEXT := '';
    updated_orders TEXT := '';
    inserted_count INT := 0;
    updated_count INT := 0;
BEGIN
    -- insert delivery_detail records based on vehicle_types
    FOR rec IN
        SELECT order_number, vehicle_type, customer_id
        FROM (
            SELECT 
                dopt.order_number,
                dopt.vehicle_type,
                vto.customer_id,
                ROW_NUMBER() OVER (
                    PARTITION BY dopt.order_number
                    ORDER BY dopt.rank ASC
                ) AS next_vehicle_rank
            FROM (
                SELECT DISTINCT order_number, customer_id
                FROM delivery_detail
                WHERE status = 'vehicle_type_timedout'
            ) vto
            JOIN delivery_option dopt
                ON dopt.order_number = vto.order_number
            LEFT JOIN delivery_detail dd
                ON dopt.order_number = dd.order_number
                AND dopt.vehicle_type = dd.vehicle_type
            WHERE dd.vehicle_type IS NULL
        ) sub
        WHERE next_vehicle_rank = 1
    LOOP
        PERFORM insert_delivery_detail(rec.customer_id, rec.order_number, rec.vehicle_type);
        inserted_count := inserted_count + 1;
        IF inserted_details <> '' THEN
            inserted_details := inserted_details || E'\n';
        END IF;
        inserted_details := inserted_details || format('Inserted: order=%s, vehicle_type=%s, customer_id=%s', rec.order_number, rec.vehicle_type, rec.customer_id);
    END LOOP;
    -- timeout delivery_detail records
    WITH
    option_types AS (
        SELECT order_number, COUNT(DISTINCT vehicle_type) AS opt_count
        FROM delivery_option
        GROUP BY order_number
    ),
    timedout_types AS (
        SELECT order_number, COUNT(DISTINCT vehicle_type) AS det_count, MIN(dtts) AS min_dtts
        FROM delivery_detail
        WHERE status = 'vehicle_type_timedout'
        GROUP BY order_number
    ),
    eligible_orders AS (
        SELECT o.order_number, t.min_dtts
        FROM option_types o
        JOIN timedout_types t ON o.order_number = t.order_number
        WHERE o.opt_count = t.det_count
    ),
    updated AS (
        UPDATE delivery_detail dd
        SET status = 'timedout'
        FROM eligible_orders eo
        WHERE dd.order_number = eo.order_number
        AND dd.status = 'vehicle_type_timedout'
        AND CURRENT_TIMESTAMP - eo.min_dtts > INTERVAL '3 minutes'
        RETURNING dd.order_number
    )
    SELECT string_agg(DISTINCT format('Updated: order=%s', order_number), E'\n'), count(*)
    INTO updated_orders, updated_count
    FROM updated;

    -- Compose and return log
    RETURN format(
        'Inserted records (%s):%s%sUpdated orders (%s):%s%s',
        inserted_count,
        CASE WHEN inserted_count > 0 THEN E'\n' ELSE ' ' END,
        COALESCE(inserted_details, ''),
        updated_count,
        CASE WHEN updated_count > 0 THEN E'\n' ELSE ' ' END,
        COALESCE(updated_orders, '')
    );
END;
$function$;

-- Definition taken from the live database on 2026-10-16 (the old repo copy is kept in _archive/init_delivery_detail_tbd.sql).
CREATE OR REPLACE FUNCTION public.init_delivery_detail(p_order_number character varying, p_customer_id character varying)
 RETURNS text
 LANGUAGE plpgsql
AS $function$
DECLARE
    v_vehicle_type varchar;
BEGIN
    -- Debug: Log the order_number being checked (now as return value)
    -- Check if order_number already exists in delivery_detail
    IF EXISTS (
        SELECT 1 FROM delivery_detail WHERE order_number = p_order_number
    ) THEN
        RETURN format('Order %s already exists in delivery_detail. Skipping insert.', p_order_number);
    END IF;

    -- Get vehicle_type from delivery_option with rank = 1
    SELECT vehicle_type INTO v_vehicle_type
    FROM delivery_option
    WHERE order_number = p_order_number AND rank = 1
    LIMIT 1;

    IF v_vehicle_type IS NULL THEN
        RETURN format('Order %s does not exist in delivery_detail, but no vehicle_type with rank=1 found in delivery_option.', p_order_number);
    END IF;

    PERFORM insert_delivery_detail(p_customer_id, p_order_number, v_vehicle_type);
    RETURN format('Order %s did not exist in delivery_detail. Inserted with vehicle_type %s.', p_order_number, v_vehicle_type);
END;
$function$;

-- Definition taken from the live database on 2026-10-16 (no repo copy existed).
CREATE OR REPLACE FUNCTION public.restaurant_confirmation_whook()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
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
$function$;

-- drop function insert_delivery_detail(p_cust_id character varying, p_order_number character varying, p_vehicle_type vehicle_type_enum)
