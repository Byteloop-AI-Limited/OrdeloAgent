/**
Migration: configured restaurant auto-accept

Adds the restaurant-level flag, records the order-local source marker, installs
the shared acceptance policy, and makes INSERT-time takeaway pickup finalization
observable. Existing restaurants remain disabled by default.
**/

-- BEGIN;
ALTER TABLE public.restaurant_master
    ADD COLUMN IF NOT EXISTS auto_accept BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE public.delivery_summary
    DROP CONSTRAINT IF EXISTS delivery_summary_rest_confirmation_method_check;

ALTER TABLE public.delivery_summary
    ADD CONSTRAINT delivery_summary_rest_confirmation_method_check
    CHECK (
        rest_confirmation_method IS NULL
        OR rest_confirmation_method IN ('manual', 'timeout', 'configured_auto')
    );

CREATE OR REPLACE FUNCTION public.resolve_initial_restaurant_acceptance(
    p_rest_ref VARCHAR,
    p_order_kind TEXT,
    p_created_at TIMESTAMP WITH TIME ZONE
)
RETURNS TABLE (
    auto_accept BOOLEAN,
    pickup_minutes INTEGER,
    pickup_time TIMESTAMP WITH TIME ZONE
)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_auto_accept BOOLEAN;
    v_rest_config_key TEXT;
    v_global_config_key TEXT;
    v_config_value TEXT;
    v_pickup_minutes INTEGER;
    v_created_at TIMESTAMP WITH TIME ZONE := COALESCE(p_created_at, CURRENT_TIMESTAMP);
BEGIN
    IF p_order_kind = 'delivery' THEN
        v_rest_config_key := UPPER(p_rest_ref) || '_DEFAULT_DELIVERY_PICKUP_TIME';
        v_global_config_key := 'DEFAULT_DELIVERY_PICKUP_TIME';
    ELSIF p_order_kind = 'takeaway' THEN
        v_rest_config_key := UPPER(p_rest_ref) || '_DEFAULT_COLLECTION_PICKUP_TIME';
        v_global_config_key := 'DEFAULT_COLLECTION_PICKUP_TIME';
    ELSE
        RAISE EXCEPTION 'Unsupported restaurant acceptance order kind: %', p_order_kind;
    END IF;

    SELECT rm.auto_accept
    INTO v_auto_accept
    FROM restaurant_master rm
    WHERE rm.rest_ref = p_rest_ref;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Restaurant acceptance policy not found for rest_ref: %', p_rest_ref;
    END IF;

    IF NOT COALESCE(v_auto_accept, FALSE) THEN
        RETURN QUERY SELECT FALSE, NULL::INTEGER, NULL::TIMESTAMP WITH TIME ZONE;
        RETURN;
    END IF;

    SELECT config_value INTO v_config_value
    FROM ordelo_config
    WHERE config_key = v_rest_config_key
    LIMIT 1;

    IF BTRIM(COALESCE(v_config_value, '')) ~ '^[1-9][0-9]*$' THEN
        BEGIN
            v_pickup_minutes := BTRIM(v_config_value)::INTEGER;
        EXCEPTION WHEN numeric_value_out_of_range THEN
            v_pickup_minutes := NULL;
        END;
    END IF;

    IF v_pickup_minutes IS NULL THEN
        SELECT config_value INTO v_config_value
        FROM ordelo_config
        WHERE config_key = v_global_config_key
        LIMIT 1;

        IF BTRIM(COALESCE(v_config_value, '')) ~ '^[1-9][0-9]*$' THEN
            BEGIN
                v_pickup_minutes := BTRIM(v_config_value)::INTEGER;
            EXCEPTION WHEN numeric_value_out_of_range THEN
                v_pickup_minutes := NULL;
            END;
        END IF;
    END IF;

    IF v_pickup_minutes IS NULL THEN
        RAISE EXCEPTION
            'Auto-accept pickup configuration is missing or invalid for rest_ref %, order_kind %',
            p_rest_ref,
            p_order_kind;
    END IF;

    RETURN QUERY
    SELECT TRUE, v_pickup_minutes, v_created_at + make_interval(mins => v_pickup_minutes);
END;
$$;

CREATE OR REPLACE FUNCTION public.init_delivery(p_cust_id VARCHAR, p_order_number VARCHAR, p_rest_ref VARCHAR DEFAULT NULL)
RETURNS TABLE (
    order_number VARCHAR, rest_id VARCHAR, rest_name TEXT, rest_lon DOUBLE PRECISION,
    rest_lat DOUBLE PRECISION, rest_address TEXT, town VARCHAR, customer_id VARCHAR,
    customer_name TEXT, customer_lon DOUBLE PRECISION, customer_lat DOUBLE PRECISION,
    customer_address TEXT, restaurant_confirmation_status VARCHAR,
    restaurant_update_dtts TIMESTAMP WITH TIME ZONE, restaurant_admin VARCHAR,
    status VARCHAR, rest_confirmation_code INTEGER, cust_confirmation_code INTEGER,
    rest_prep_time_minutes INTEGER, rest_confirmation_method VARCHAR,
    restaurant_msg_id VARCHAR, rider_msg_id VARCHAR, customer_msg_id VARCHAR,
    pickup_time TIMESTAMP WITH TIME ZONE, pickup_date DATE, rest_ref VARCHAR,
    dt DATE, dtts TIMESTAMP WITH TIME ZONE, redispatch_dtts TIMESTAMP WITH TIME ZONE
) AS $$
DECLARE
    v_rest_ref VARCHAR := COALESCE(p_rest_ref, SPLIT_PART(p_order_number, '-', 1));
    v_rest_id VARCHAR(12); v_rest_name TEXT; v_rest_lon DOUBLE PRECISION;
    v_rest_lat DOUBLE PRECISION; v_rest_address TEXT; v_town VARCHAR(255);
    v_customer_name TEXT; v_customer_lon DOUBLE PRECISION; v_customer_lat DOUBLE PRECISION;
    v_customer_address TEXT; v_salt_number INTEGER; v_rest_confirmation_code INTEGER;
    v_cust_confirmation_code INTEGER; v_created_at TIMESTAMP WITH TIME ZONE := CURRENT_TIMESTAMP;
    v_auto_accept BOOLEAN; v_pickup_minutes INTEGER; v_pickup_time TIMESTAMP WITH TIME ZONE;
BEGIN
    SELECT rm.rest_id, rm.rest_name, rm.lon, rm.lat,
           TRIM(CONCAT_WS(' ', rm.house_number, rm.building_name, rm.street_name, rm.city, rm.postcode)), rm.city
    INTO v_rest_id, v_rest_name, v_rest_lon, v_rest_lat, v_rest_address, v_town
    FROM restaurant_master rm WHERE rm.rest_ref = v_rest_ref;
    IF NOT FOUND THEN RAISE EXCEPTION 'Restaurant details not found for rest_ref: %', v_rest_ref; END IF;

    SELECT cm.cust_name, cm.lon, cm.lat,
           TRIM(CONCAT_WS(' ', cm.house_number, cm.building_name, cm.street_name, cm.city, cm.postcode))
    INTO v_customer_name, v_customer_lon, v_customer_lat, v_customer_address
    FROM customer_master cm WHERE cm.cust_id = p_cust_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'Customer details not found for cust_id: %', p_cust_id; END IF;

    SELECT config_value::INTEGER INTO v_salt_number FROM ordelo_config
    WHERE config_key = 'CONFIRMATION_CODE_SALT' LIMIT 1;
    IF NOT FOUND THEN RAISE EXCEPTION 'Salt config not found for CONFIRMATION_CODE_SALT'; END IF;

    v_rest_confirmation_code := floor(random() * (90 - (v_salt_number - 100) + 1) + (v_salt_number - 100))::INT;
    v_cust_confirmation_code := v_salt_number - v_rest_confirmation_code;
    SELECT
        acceptance.auto_accept,
        acceptance.pickup_minutes,
        acceptance.pickup_time
    INTO v_auto_accept, v_pickup_minutes, v_pickup_time
    FROM public.resolve_initial_restaurant_acceptance(
        v_rest_ref,
        'delivery',
        v_created_at
    ) AS acceptance;

    RETURN QUERY INSERT INTO delivery_summary (
        order_number, rest_id, rest_name, rest_lon, rest_lat, rest_address, town,
        customer_id, customer_name, customer_lon, customer_lat, customer_address,
        restaurant_confirmation_status, restaurant_update_dtts, status,
        rest_confirmation_code, cust_confirmation_code, rest_prep_time_minutes,
        rest_confirmation_method, pickup_time, dtts
    ) VALUES (
        p_order_number, v_rest_id, v_rest_name, v_rest_lon, v_rest_lat, v_rest_address, v_town,
        p_cust_id, v_customer_name, v_customer_lon, v_customer_lat, v_customer_address,
        CASE WHEN v_auto_accept THEN 'auto_accept' ELSE 'restaurant_unconfirmed' END,
        CASE WHEN v_auto_accept THEN v_created_at ELSE NULL END,
        CASE WHEN v_auto_accept THEN 'unassigned' ELSE 'restaurant_unconfirmed' END,
        v_rest_confirmation_code, v_cust_confirmation_code, v_pickup_minutes,
        CASE WHEN v_auto_accept THEN 'configured_auto' ELSE NULL END, v_pickup_time, v_created_at
    ) RETURNING *;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION public.init_takeaway(p_cust_id VARCHAR, p_order_number VARCHAR, p_rest_ref VARCHAR DEFAULT NULL)
RETURNS TABLE (
    order_number VARCHAR, rest_id VARCHAR, rest_name TEXT, rest_address TEXT, town VARCHAR,
    customer_id VARCHAR, customer_name TEXT, restaurant_confirmation_status VARCHAR,
    restaurant_update_dtts TIMESTAMP WITH TIME ZONE, restaurant_admin VARCHAR, status VARCHAR,
    rest_confirmation_code INTEGER, rest_prep_time_minutes INTEGER, rest_confirmation_method VARCHAR,
    restaurant_msg_id VARCHAR, customer_msg_id VARCHAR, pickup_time TIMESTAMP WITH TIME ZONE,
    pickup_date DATE, rest_ref VARCHAR, dt DATE, dtts TIMESTAMP WITH TIME ZONE
) AS $$
DECLARE
    v_rest_ref VARCHAR := COALESCE(p_rest_ref, SPLIT_PART(p_order_number, '-', 1));
    v_rest_id VARCHAR(12); v_rest_name TEXT; v_rest_address TEXT; v_town VARCHAR(255);
    v_customer_name TEXT; v_salt_number INTEGER; v_rest_confirmation_code INTEGER;
    v_created_at TIMESTAMP WITH TIME ZONE := CURRENT_TIMESTAMP; v_auto_accept BOOLEAN;
    v_pickup_minutes INTEGER; v_pickup_time TIMESTAMP WITH TIME ZONE;
BEGIN
    SELECT rm.rest_id, rm.rest_name,
           TRIM(CONCAT_WS(' ', rm.house_number, rm.building_name, rm.street_name, rm.city, rm.postcode)), rm.city
    INTO v_rest_id, v_rest_name, v_rest_address, v_town
    FROM restaurant_master rm WHERE rm.rest_ref = v_rest_ref;
    IF NOT FOUND THEN RAISE EXCEPTION 'Restaurant details not found for rest_ref: %', v_rest_ref; END IF;

    SELECT cm.cust_name INTO v_customer_name FROM customer_master cm WHERE cm.cust_id = p_cust_id;
    IF NOT FOUND OR v_customer_name IS NULL THEN v_customer_name := p_cust_id; END IF;

    SELECT config_value::INTEGER INTO v_salt_number FROM ordelo_config
    WHERE config_key = 'CONFIRMATION_CODE_SALT' LIMIT 1;
    IF NOT FOUND THEN RAISE EXCEPTION 'Salt config not found for CONFIRMATION_CODE_SALT'; END IF;

    v_rest_confirmation_code := floor(random() * (90 - (v_salt_number - 100) + 1) + (v_salt_number - 100))::INT;
    SELECT
        acceptance.auto_accept,
        acceptance.pickup_minutes,
        acceptance.pickup_time
    INTO v_auto_accept, v_pickup_minutes, v_pickup_time
    FROM public.resolve_initial_restaurant_acceptance(
        v_rest_ref,
        'takeaway',
        v_created_at
    ) AS acceptance;

    RETURN QUERY INSERT INTO takeaway_summary (
        order_number, rest_id, rest_name, rest_address, town, customer_id, customer_name,
        restaurant_confirmation_status, restaurant_update_dtts, status, rest_confirmation_code,
        rest_prep_time_minutes, rest_confirmation_method, pickup_time, dtts
    ) VALUES (
        p_order_number, v_rest_id, v_rest_name, v_rest_address, v_town, p_cust_id, v_customer_name,
        CASE WHEN v_auto_accept THEN 'auto_accept' ELSE 'restaurant_unconfirmed' END,
        CASE WHEN v_auto_accept THEN v_created_at ELSE NULL END,
        CASE WHEN v_auto_accept THEN 'pickup_confirmed' ELSE 'restaurant_unconfirmed' END,
        v_rest_confirmation_code, v_pickup_minutes,
        CASE WHEN v_auto_accept THEN 'configured_auto' ELSE NULL END, v_pickup_time, v_created_at
    ) RETURNING *;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_takeaway_pickup_time_insert ON public.takeaway_summary;
CREATE TRIGGER trigger_takeaway_pickup_time_insert
AFTER INSERT ON public.takeaway_summary
FOR EACH ROW
WHEN (NEW.pickup_time IS NOT NULL)
EXECUTE FUNCTION public.takeaway_pickup_time_whook();

-- COMMIT;
