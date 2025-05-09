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


-- drop function insert_delivery_detail(p_cust_id character varying, p_order_number character varying, p_vehicle_type vehicle_type_enum)