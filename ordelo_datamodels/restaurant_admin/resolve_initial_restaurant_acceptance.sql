-- See also (paths under ordelo_datamodels/): auto-accepted orders reach Telegram admins as a notice (see restaurant_admin/restaurant_ready_adjust_notices.sql) and as order cards (telegram/t_order_alerts.sql).
/**
Restaurant Acceptance Policy – Initial Summary State

Purpose:
    - Resolve whether a restaurant bypasses manual confirmation at order creation.
    - Resolve the restaurant-specific pickup duration with a global fallback.
    - Return a single, transaction-local pickup timestamp for delivery and takeaway
      initializers.

Interface:
    resolve_initial_restaurant_acceptance(rest_ref, order_kind, created_at)
      -> (auto_accept, pickup_minutes, pickup_time)

Failure behaviour:
    - Disabled restaurants return false with NULL pickup fields.
    - Enabled restaurants require a positive whole-minute restaurant-specific or
      global configuration; otherwise the caller's transaction fails.
**/
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

    SELECT config_value
    INTO v_config_value
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
        SELECT config_value
        INTO v_config_value
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
