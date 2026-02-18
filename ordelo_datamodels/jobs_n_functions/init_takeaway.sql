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

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Customer details not found for cust_id: %', p_cust_id;
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
        status,
        rest_confirmation_code
    ) VALUES (
        p_order_number,
        v_rest_id,
        v_rest_name,
        v_rest_address,
        v_town,
        p_cust_id,
        v_customer_name,
        'restaurant_unconfirmed',
        'restaurant_unconfirmed',
        v_rest_confirmation_code
    )
    RETURNING *;
END;
$$ LANGUAGE plpgsql;
