-- =============================================================================================
-- ordelo_datamodels/restaurant_admin/resolve_initial_restaurant_acceptance.sql
-- Decide at order creation whether the restaurant auto-accepts, and with which pickup time.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     resolve_initial_restaurant_acceptance(p_rest_ref character varying, p_order_kind text, p_created_at timestamp with time zone) -> TABLE(auto_accept boolean, pickup_minutes integer, pickup_time timestamp with time zone)
--                   Return (auto_accept, pickup_minutes, pickup_time) for a new order of kind 'delivery' or 'collection'.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none (reads restaurant_master and ordelo_config)
-- HOW IT FITS   Restaurant confirmation, delivery and takeaway alike:
--                 new order -> init_delivery() / init_takeaway() -> resolve_initial_restaurant_acceptance():
--                     auto_accept restaurants: order starts accepted with a default pickup time (no prompt)
--                     otherwise: 'restaurant_unconfirmed' -> trigger -> admins prompted (WhatsApp buttons; Telegram order cards)
--                 admin taps Accept / Decline -> restaurant_order_decide(); picks a pickup time -> restaurant_order_set_pickup()
--                     (Telegram taps go through t_order_decide() / t_order_set_pickup(), which authorise the person first)
--                 no answer -> process_restaurant_confirmation() (cron 10 s) -> 'restaurant_timedout' -> trigger -> Python sets a default
--                     pickup time and makes the order dispatchable (delivery_hooks._handle_restaurant_timedout)
--                 morning check -> enquire_admin_availability() (cron 11:00 UTC) asks admins whether the restaurant is open today.
-- LIFECYCLE     none
-- CALLED BY     resolve_initial_restaurant_acceptance:
--                 sql       init_delivery() (delivery/init_delivery.sql)
--                 sql       init_takeaway() (takeaway/init_takeaway.sql)
-- PYTHON MODEL  none
-- SECURITY      resolve_initial_restaurant_acceptance(): executable by PUBLIC (default)
-- TESTS         tests/ordelo_datamodels/test_auto_accept_sql.py
-- GOTCHAS       An auto-accepting restaurant must have a positive whole-minute <REST>_DEFAULT_DELIVERY_PICKUP_TIME /
--                 <REST>_DEFAULT_COLLECTION_PICKUP_TIME (or the global DEFAULT_* key), otherwise order creation fails (RAISE).
--               Auto-accepted orders still reach Telegram admins as a notice and as order cards.
-- SEE ALSO      delivery/init_delivery.sql
--               takeaway/init_takeaway.sql
--               core/restaurant_master.sql (auto_accept)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function resolve_initial_restaurant_acceptance(p_rest_ref character varying, p_order_kind text, p_created_at timestamp with time zone) -> TABLE(auto_accept boolean, pickup_minutes integer, pickup_time timestamp with time zone)
--   Return (auto_accept, pickup_minutes, pickup_time) for a new order of kind 'delivery' or 'collection'.
--   Disabled restaurants return false with NULL pickup fields; enabled ones need a valid restaurant-specific or global
--   default pickup time, else RAISE (the caller's transaction fails).
--   Data: reads ordelo_config, restaurant_master.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.resolve_initial_restaurant_acceptance (p_rest_ref varchar, p_order_kind text, p_created_at timestamp with time zone)
    RETURNS TABLE (
        auto_accept boolean,
        pickup_minutes integer,
        pickup_time timestamp with time zone)
    LANGUAGE plpgsql
    STABLE
    AS $$
DECLARE
    v_auto_accept boolean;
    v_rest_config_key text;
    v_global_config_key text;
    v_config_value text;
    v_pickup_minutes integer;
    v_created_at timestamp with time zone := COALESCE(p_created_at, CURRENT_TIMESTAMP);
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

    SELECT
        rm.auto_accept INTO v_auto_accept
    FROM
        restaurant_master rm
    WHERE
        rm.rest_ref = p_rest_ref;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Restaurant acceptance policy not found for rest_ref: %', p_rest_ref;
    END IF;

    IF NOT COALESCE(v_auto_accept, FALSE) THEN
        RETURN QUERY
        SELECT
            FALSE,
            NULL::integer,
            NULL::timestamp WITH TIME ZONE;
        RETURN;
    END IF;

    SELECT
        config_value INTO v_config_value
    FROM
        ordelo_config
    WHERE
        config_key = v_rest_config_key
    LIMIT 1;

    IF BTRIM(COALESCE(v_config_value, '')) ~ '^[1-9][0-9]*$' THEN
        BEGIN
            v_pickup_minutes := BTRIM(v_config_value)::integer;
        EXCEPTION
            WHEN numeric_value_out_of_range THEN
                v_pickup_minutes := NULL;
        END;
    END IF;

    IF v_pickup_minutes IS NULL THEN
        SELECT
            config_value INTO v_config_value
        FROM
            ordelo_config
        WHERE
            config_key = v_global_config_key
        LIMIT 1;

        IF BTRIM(COALESCE(v_config_value, '')) ~ '^[1-9][0-9]*$' THEN
            BEGIN
                v_pickup_minutes := BTRIM(v_config_value)::integer;
            EXCEPTION
                WHEN numeric_value_out_of_range THEN
                    v_pickup_minutes := NULL;
            END;
        END IF;
END IF;

IF v_pickup_minutes IS NULL THEN
    RAISE EXCEPTION 'Auto-accept pickup configuration is missing or invalid for rest_ref %, order_kind %', p_rest_ref, p_order_kind;
    END IF;

    RETURN QUERY
    SELECT
        TRUE,
        v_pickup_minutes,
        v_created_at + make_interval(mins => v_pickup_minutes);
END;

$$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.resolve_initial_restaurant_acceptance (p_rest_ref character varying, p_order_kind text, p_created_at timestamp with time zone) IS 'Return (auto_accept, pickup_minutes, pickup_time) for a new order of kind ''delivery'' or ''collection''.';
