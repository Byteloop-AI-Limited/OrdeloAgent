-- See also (paths under ordelo_datamodels/): keep the RETURNING list in step with the RETURNS TABLE list (never RETURNING *: see restaurant_admin/restaurant_ready_adjust_notices.sql).
/**
Takeaway Initiation – Entry Point in Takeaway Confirmation Workflow

Purpose:
    - Initialize takeaway confirmation details by creating a record in `takeaway_summary`.
    - Generate restaurant confirmation code.

Invocation:
    - Called from app hooks to initiate takeaway confirmation workflow.
**/
DROP FUNCTION IF EXISTS public.init_takeaway;

CREATE OR REPLACE FUNCTION public.init_takeaway(p_cust_id VARCHAR, p_order_number VARCHAR, p_rest_ref VARCHAR DEFAULT NULL)
RETURNS TABLE (
    order_number VARCHAR,
    rest_id VARCHAR,
    rest_name TEXT,
    rest_address TEXT,
    town VARCHAR,
    customer_id VARCHAR,
    customer_name TEXT,
    restaurant_confirmation_status VARCHAR,
    restaurant_update_dtts TIMESTAMP WITH TIME ZONE,
    restaurant_admin VARCHAR,
    status VARCHAR,
    rest_confirmation_code INTEGER,
    rest_prep_time_minutes INTEGER,
    rest_confirmation_method VARCHAR,
    restaurant_msg_id VARCHAR,
    customer_msg_id VARCHAR,
    pickup_time TIMESTAMP WITH TIME ZONE,
    pickup_date DATE,
    rest_ref VARCHAR,
    dt DATE,
    dtts TIMESTAMP WITH TIME ZONE
) AS $$
DECLARE
    v_rest_ref VARCHAR;
    v_rest_id VARCHAR(12);
    v_rest_name TEXT;
    v_rest_address TEXT;
    v_town VARCHAR(255);
    v_customer_name TEXT;
    v_salt_number INTEGER;
    v_rest_confirmation_code INTEGER;
    v_created_at TIMESTAMP WITH TIME ZONE := CURRENT_TIMESTAMP;
    v_auto_accept BOOLEAN;
    v_pickup_minutes INTEGER;
    v_pickup_time TIMESTAMP WITH TIME ZONE;
BEGIN
    v_rest_ref := COALESCE(p_rest_ref, SPLIT_PART(p_order_number, '-', 1));

    SELECT
        rm.rest_id,
        rm.rest_name,
        TRIM(CONCAT_WS(' ', rm.house_number, rm.building_name, rm.street_name, rm.city, rm.postcode)),
        rm.city
    INTO
        v_rest_id,
        v_rest_name,
        v_rest_address,
        v_town
    FROM restaurant_master rm
    WHERE rm.rest_ref = v_rest_ref;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Restaurant details not found for rest_ref: %', v_rest_ref;
    END IF;

    SELECT
        cm.cust_name
    INTO
        v_customer_name
    FROM customer_master cm
    WHERE cm.cust_id = p_cust_id;

    IF NOT FOUND OR v_customer_name IS NULL THEN
        v_customer_name := p_cust_id;
    END IF;

    SELECT (config_value)::INTEGER
    INTO v_salt_number
    FROM ordelo_config
    WHERE config_key = 'CONFIRMATION_CODE_SALT'
    LIMIT 1;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Salt config not found for CONFIRMATION_CODE_SALT';
    END IF;

    v_rest_confirmation_code := floor(
        random() * (90 - (v_salt_number - 100) + 1) + (v_salt_number - 100)
    )::INT;

    SELECT
        acceptance.auto_accept,
        acceptance.pickup_minutes,
        acceptance.pickup_time
    INTO
        v_auto_accept,
        v_pickup_minutes,
        v_pickup_time
    FROM public.resolve_initial_restaurant_acceptance(
        v_rest_ref,
        'takeaway',
        v_created_at
    ) AS acceptance;

    RETURN QUERY
    INSERT INTO takeaway_summary (
        order_number,
        rest_id,
        rest_name,
        rest_address,
        town,
        customer_id,
        customer_name,
        restaurant_confirmation_status,
        restaurant_update_dtts,
        status,
        rest_confirmation_code,
        rest_prep_time_minutes,
        rest_confirmation_method,
        pickup_time,
        dtts
    ) VALUES (
        p_order_number,
        v_rest_id,
        v_rest_name,
        v_rest_address,
        v_town,
        p_cust_id,
        v_customer_name,
        CASE WHEN v_auto_accept THEN 'auto_accept' ELSE 'restaurant_unconfirmed' END,
        CASE WHEN v_auto_accept THEN v_created_at ELSE NULL END,
        CASE WHEN v_auto_accept THEN 'pickup_confirmed' ELSE 'restaurant_unconfirmed' END,
        v_rest_confirmation_code,
        v_pickup_minutes,
        CASE WHEN v_auto_accept THEN 'configured_auto' ELSE NULL END,
        v_pickup_time,
        v_created_at
    )
    -- Explicit list, qualified by table: RETURNING * breaks ("structure of query does not match function result type")
    -- the moment a column is added to takeaway_summary, and bare names clash with the RETURNS TABLE output variables.
    RETURNING
        takeaway_summary.order_number,
        takeaway_summary.rest_id,
        takeaway_summary.rest_name,
        takeaway_summary.rest_address,
        takeaway_summary.town,
        takeaway_summary.customer_id,
        takeaway_summary.customer_name,
        takeaway_summary.restaurant_confirmation_status,
        takeaway_summary.restaurant_update_dtts,
        takeaway_summary.restaurant_admin,
        takeaway_summary.status,
        takeaway_summary.rest_confirmation_code,
        takeaway_summary.rest_prep_time_minutes,
        takeaway_summary.rest_confirmation_method,
        takeaway_summary.restaurant_msg_id,
        takeaway_summary.customer_msg_id,
        takeaway_summary.pickup_time,
        takeaway_summary.pickup_date,
        takeaway_summary.rest_ref,
        takeaway_summary.dt,
        takeaway_summary.dtts;
END;
$$ LANGUAGE plpgsql;
