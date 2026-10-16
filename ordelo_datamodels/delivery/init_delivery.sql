-- See also (paths under ordelo_datamodels/): keep the RETURNING list in step with the RETURNS TABLE list (never RETURNING *: the kitchen columns in restaurant_admin/restaurant_ready_adjust_notices.sql were added to delivery_summary and broke it once).
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
DROP FUNCTION IF EXISTS public.init_delivery (VARCHAR, VARCHAR, VARCHAR);

CREATE OR REPLACE FUNCTION public.init_delivery (p_cust_id varchar, p_order_number varchar, p_rest_ref varchar DEFAULT NULL)
    RETURNS TABLE (
        order_number varchar,
        rest_id varchar,
        rest_name text,
        rest_lon double precision,
        rest_lat double precision,
        rest_address text,
        town varchar,
        customer_id varchar,
        customer_name text,
        customer_lon double precision,
        customer_lat double precision,
        customer_address text,
        restaurant_confirmation_status varchar,
        restaurant_update_dtts timestamp with time zone,
        restaurant_admin varchar,
        status varchar,
        rest_confirmation_code integer,
        cust_confirmation_code integer,
        rest_prep_time_minutes integer,
        rest_confirmation_method varchar,
        restaurant_msg_id varchar,
        rider_msg_id varchar,
        customer_msg_id varchar,
        pickup_time timestamp with time zone,
        pickup_date date,
        rest_ref varchar,
        dt date,
        dtts timestamp with time zone,
        redispatch_dtts timestamp with time zone
    )
    AS $$
DECLARE
    v_rest_ref varchar;
    v_rest_id varchar(12);
    v_rest_name text;
    v_rest_lon double precision;
    v_rest_lat double precision;
    v_rest_address text;
    v_town varchar(255);
    v_customer_name text;
    v_customer_lon double precision;
    v_customer_lat double precision;
    v_customer_address text;
    v_salt_number integer;
    v_rest_confirmation_code integer;
    v_cust_confirmation_code integer;
    v_created_at timestamp with time zone := CURRENT_TIMESTAMP;
    v_auto_accept boolean;
    v_pickup_minutes integer;
    v_pickup_time timestamp with time zone;
BEGIN
    -- Derive rest_ref from order_number, or use provided value
    v_rest_ref := COALESCE(p_rest_ref, SPLIT_PART(p_order_number, '-', 1));
    -- Fetch restaurant details
    SELECT
        rm.rest_id,
        rm.rest_name,
        rm.lon,
        rm.lat,
        TRIM(CONCAT_WS(' ', rm.house_number, rm.building_name, rm.street_name, rm.city, rm.postcode)),
        rm.city INTO v_rest_id,
        v_rest_name,
        v_rest_lon,
        v_rest_lat,
        v_rest_address,
        v_town
    FROM
        restaurant_master rm
    WHERE
        rm.rest_ref = v_rest_ref;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Restaurant details not found for rest_ref: %', v_rest_ref;
    END IF;
    -- Fetch customer details
    SELECT
        cm.cust_name,
        cm.lon,
        cm.lat,
        TRIM(CONCAT_WS(' ', cm.house_number, cm.building_name, cm.street_name, cm.city, cm.postcode)) INTO v_customer_name,
        v_customer_lon,
        v_customer_lat,
        v_customer_address
    FROM
        customer_master cm
    WHERE
        cm.cust_id = p_cust_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Customer details not found for cust_id: %', p_cust_id;
    END IF;
    -- Fetch salt from config
    SELECT
        (config_value)::integer INTO v_salt_number
    FROM
        ordelo_config
    WHERE
        config_key = 'CONFIRMATION_CODE_SALT'
    LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Salt config not found for CONFIRMATION_CODE_SALT';
    END IF;
    -- Generate confirmation codes
    v_rest_confirmation_code := floor(random() * (90 - (v_salt_number - 100) + 1) + (v_salt_number - 100))::int;
    v_cust_confirmation_code := v_salt_number - v_rest_confirmation_code;

    SELECT
        acceptance.auto_accept,
        acceptance.pickup_minutes,
        acceptance.pickup_time INTO v_auto_accept,
        v_pickup_minutes,
        v_pickup_time
    FROM
        public.resolve_initial_restaurant_acceptance (v_rest_ref, 'delivery', v_created_at) AS acceptance;
    -- Insert summary record and return the complete record
    -- Configured auto-accept orders bypass the confirmation workflow with a
    -- non-null pickup_time; all other orders retain the existing flow.
    RETURN QUERY INSERT INTO delivery_summary (order_number, rest_id, rest_name, rest_lon, rest_lat, rest_address, town, customer_id, customer_name, customer_lon, customer_lat, customer_address, restaurant_confirmation_status, restaurant_update_dtts, status, rest_confirmation_code, cust_confirmation_code, rest_prep_time_minutes, rest_confirmation_method, pickup_time, dtts)
        VALUES (p_order_number, v_rest_id, v_rest_name, v_rest_lon, v_rest_lat, v_rest_address, v_town, p_cust_id, v_customer_name, v_customer_lon, v_customer_lat, v_customer_address, CASE WHEN v_auto_accept THEN
                'auto_accept'
            ELSE
                'restaurant_unconfirmed'
            END, CASE WHEN v_auto_accept THEN
                v_created_at
            ELSE
                NULL
            END, CASE WHEN v_auto_accept THEN
                'unassigned'
            ELSE
                'restaurant_unconfirmed'
            END, v_rest_confirmation_code, v_cust_confirmation_code, v_pickup_minutes, CASE WHEN v_auto_accept THEN
                'configured_auto'
            ELSE
                NULL
            END, v_pickup_time, v_created_at)
        -- Explicit list, qualified by table: RETURNING * breaks ("structure of query does not match function result type")
        -- the moment a column is added to delivery_summary, and bare names clash with the RETURNS TABLE output variables.
    RETURNING
        delivery_summary.order_number, delivery_summary.rest_id, delivery_summary.rest_name, delivery_summary.rest_lon, delivery_summary.rest_lat, delivery_summary.rest_address, delivery_summary.town, delivery_summary.customer_id, delivery_summary.customer_name, delivery_summary.customer_lon, delivery_summary.customer_lat, delivery_summary.customer_address, delivery_summary.restaurant_confirmation_status, delivery_summary.restaurant_update_dtts, delivery_summary.restaurant_admin, delivery_summary.status, delivery_summary.rest_confirmation_code, delivery_summary.cust_confirmation_code, delivery_summary.rest_prep_time_minutes, delivery_summary.rest_confirmation_method, delivery_summary.restaurant_msg_id, delivery_summary.rider_msg_id, delivery_summary.customer_msg_id, delivery_summary.pickup_time, delivery_summary.pickup_date, delivery_summary.rest_ref, delivery_summary.dt, delivery_summary.dtts, delivery_summary.redispatch_dtts;
    -- kick off process_delivery; May be add condition on pickup_time
    -- PERFORM process_delivery();
END;
$$
LANGUAGE plpgsql;
