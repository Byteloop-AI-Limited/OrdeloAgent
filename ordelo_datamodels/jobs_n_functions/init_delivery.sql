/**
Delivery Initiation – Entry Point in Delivery Workflow

Where This Fits in the Journey:
    - This function is the first step in the delivery agent workflow. It is invoked by an external service when a new delivery order is created.
    - As per the journey outlined in handwritten_design.md:
        • Step 1: init_delivery – Creates the delivery_summary and eagerly calls process_delivery().
        • Step 2: process_delivery – Handles creation of delivery_detail records and manages dispatch logic.
        • Step 3+: Downstream jobs and triggers handle dispatch creation, assignment, inflight tracking, and notifications.

Invocation:
    - Called by an external service (payment_hooks-> handle_payment_complete) to initiate the delivery process.

Purpose:
    - Initialize delivery details by creating a record in `delivery_summary`.
    - Generate confirmation codes for both the restaurant and the customer.
    - Eagerly execute process_delivery to ensure dispatch creation is immediate, not delayed by scheduled jobs.

Dependencies:
    - Reads from: `customer_master`, `restaurant_master`, `ordelo_config`.
    - Writes to: `delivery_summary`.
    - Calls: `process_delivery()`.

Side Effects:
    - None directly, but triggers downstream workflow via process_delivery().

See also: jobs_n_functions/handwritten_design.md for the full delivery journey.
**/

DROP FUNCTION public.init_delivery;

CREATE OR REPLACE FUNCTION public.init_delivery(p_cust_id VARCHAR, p_order_number VARCHAR)
RETURNS TABLE (
    order_number VARCHAR,
    rest_id VARCHAR,
    rest_name TEXT,
    rest_lon DOUBLE PRECISION,
    rest_lat DOUBLE PRECISION,
    rest_address TEXT,
    town VARCHAR,
    customer_id VARCHAR,
    customer_name TEXT,
    customer_lon DOUBLE PRECISION,
    customer_lat DOUBLE PRECISION,
    customer_address TEXT,
    status VARCHAR,
    rest_confirmation_code INTEGER,
    cust_confirmation_code INTEGER,
    rest_confirmed_at TIMESTAMP WITH TIME ZONE,
    rest_prep_time_minutes INTEGER,
    rest_confirmation_method VARCHAR,
    pickup_time TIMESTAMP WITH TIME ZONE,
    pickup_date DATE,
    dt DATE,
    dtts TIMESTAMP WITH TIME ZONE
) AS $$
DECLARE
    v_rest_ref VARCHAR;
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
    v_salt_number INTEGER;
    v_rest_confirmation_code INTEGER;
    v_cust_confirmation_code INTEGER;
BEGIN
    -- Derive rest_ref from order_number
    v_rest_ref := SPLIT_PART(p_order_number, '-', 1);

    -- Fetch restaurant details
    SELECT
        rm.rest_id,
        rm.rest_name,
        rm.lon,
        rm.lat,
        TRIM(CONCAT_WS(' ', rm.house_number, rm.building_name, rm.street_name, rm.city, rm.postcode)),
        rm.city
    INTO
        v_rest_id,
        v_rest_name,
        v_rest_lon,
        v_rest_lat,
        v_rest_address,
        v_town
    FROM restaurant_master rm
    WHERE rm.rest_ref = v_rest_ref;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Restaurant details not found for rest_ref: %', v_rest_ref;
    END IF;

    -- Fetch customer details
    SELECT
        cm.cust_name,
        cm.lon,
        cm.lat,
        TRIM(CONCAT_WS(' ', cm.house_number, cm.building_name, cm.street_name, cm.city, cm.postcode))
    INTO
        v_customer_name,
        v_customer_lon,
        v_customer_lat,
        v_customer_address
    FROM customer_master cm
    WHERE cm.cust_id = p_cust_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Customer details not found for cust_id: %', p_cust_id;
    END IF;

    -- Fetch salt from config
    SELECT (config_value)::INTEGER
    INTO v_salt_number
    FROM ordelo_config
    WHERE config_key = 'CONFIRMATION_CODE_SALT'
    LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Salt config not found for CONFIRMATION_CODE_SALT';
    END IF;

    -- Generate confirmation codes
    v_rest_confirmation_code := floor(random() * (90 - (v_salt_number - 100) + 1) + (v_salt_number - 100))::INT;
    v_cust_confirmation_code := v_salt_number - v_rest_confirmation_code;

    -- Insert summary record and return the complete record
    RETURN QUERY
    INSERT INTO delivery_summary (
        order_number,
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
        status,
        rest_confirmation_code,
        cust_confirmation_code
    ) VALUES (
        p_order_number,
        v_rest_id,
        v_rest_name,
        v_rest_lon,
        v_rest_lat,
        v_rest_address,
        v_town,
        p_cust_id,
        v_customer_name,
        v_customer_lon,
        v_customer_lat,
        v_customer_address,
        'restaurant_unconfirmed',
        v_rest_confirmation_code,
        v_cust_confirmation_code
    )
    RETURNING *;
    
    -- kick off process_delivery; May be add condition on pickup_time
    -- PERFORM process_delivery();
END;
$$ LANGUAGE plpgsql;
