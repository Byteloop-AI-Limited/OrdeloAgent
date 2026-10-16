-- =============================================================================================
-- ordelo_datamodels/takeaway/init_takeaway.sql
-- Create the takeaway_summary row for a paid collection order.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     init_takeaway(p_cust_id character varying, p_order_number character varying, p_rest_ref character varying) -> TABLE(order_number character varying, rest_id character varying, rest_name text, rest_address text, town character varying, customer_id character varying, customer_name text, restaurant_confirmation_status character varying, restaurant_update_dtts timestamp with time zone, restaurant_admin character varying, status character varying, rest_confirmation_code integer, rest_prep_time_minutes integer, rest_confirmation_method character varying, restaurant_msg_id character varying, customer_msg_id character varying, pickup_time timestamp with time zone, pickup_date date, rest_ref character varying, dt date, dtts timestamp with time zone)
--                   Create the takeaway_summary row for an order and return it.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call inserts one takeaway_summary row (fires the restaurant prompt trigger, and the pickup-time trigger when auto-accepted).
-- HOW IT FITS   Takeaway (collection) order journey (takeaway_summary.status):
--                 1 create   /takeaway-hooks/init-takeaway-order -> init_takeaway(): 'restaurant_unconfirmed', or 'pickup_confirmed' with a
--                            pickup time when the restaurant auto-accepts.
--                 2 confirm  trigger_takeaway_restaurant_updates -> POST /takeaway-hooks/restaurant-confirmation-request -> admins asked.
--                            restaurant_order_decide() / restaurant_order_set_pickup() record the decision and pickup time
--                            ('pickup_confirmed'); process_restaurant_confirmation() (cron 10 s) times out unanswered orders.
--                 3 notify   pickup_time first set (or set at insert) -> trigger_takeaway_pickup_time_set / _insert ->
--                            POST /takeaway-hooks/pickup-time-updated -> customer told when to collect.
--                 4 ready    restaurant_order_ready() (WhatsApp or Telegram Ready) sets ready_at / ready_by; customer told.
-- LIFECYCLE     'restaurant_unconfirmed', or 'pickup_confirmed' + pickup_time + 'configured_auto' when the restaurant auto-accepts.
-- CALLED BY     init_takeaway:
--                 python    watomation/routers/takeaway_hooks.py: init_takeaway_summary()
-- PYTHON MODEL  none
-- SECURITY      init_takeaway(): executable by PUBLIC (default)
-- TESTS         tests/test_sql_returning_star.py
-- GOTCHAS       RETURNING lists the columns: never RETURNING * (SQLSTATE 42804 once the table gains a column).
-- SEE ALSO      takeaway/takeaway_summary.sql
--               restaurant_admin/resolve_initial_restaurant_acceptance.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function init_takeaway(p_cust_id character varying, p_order_number character varying, p_rest_ref character varying) -> TABLE(order_number character varying, rest_id character varying, rest_name text, rest_address text, town character varying, customer_id character varying, customer_name text, restaurant_confirmation_status character varying, restaurant_update_dtts timestamp with time zone, restaurant_admin character varying, status character varying, rest_confirmation_code integer, rest_prep_time_minutes integer, rest_confirmation_method character varying, restaurant_msg_id character varying, customer_msg_id character varying, pickup_time timestamp with time zone, pickup_date date, rest_ref character varying, dt date, dtts timestamp with time zone)
--   Create the takeaway_summary row for an order and return it.
--   Reads restaurant_master, customer_master and the CONFIRMATION_CODE_SALT; asks resolve_initial_restaurant_acceptance()
--   whether to auto-accept. Called by /takeaway-hooks/init-takeaway-order (takeaway_hooks.py).
--   Data: reads customer_master, ordelo_config, restaurant_master; writes takeaway_summary; calls resolve_initial_restaurant_acceptance().
-- ---------------------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS public.init_takeaway;

CREATE OR REPLACE FUNCTION public.init_takeaway (p_cust_id varchar, p_order_number varchar, p_rest_ref varchar DEFAULT NULL)
    RETURNS TABLE (
        order_number varchar,
        rest_id varchar,
        rest_name text,
        rest_address text,
        town varchar,
        customer_id varchar,
        customer_name text,
        restaurant_confirmation_status varchar,
        restaurant_update_dtts timestamp with time zone,
        restaurant_admin varchar,
        status varchar,
        rest_confirmation_code integer,
        rest_prep_time_minutes integer,
        rest_confirmation_method varchar,
        restaurant_msg_id varchar,
        customer_msg_id varchar,
        pickup_time timestamp with time zone,
        pickup_date date,
        rest_ref varchar,
        dt date,
        dtts timestamp with time zone
    )
    AS $$
DECLARE
    v_rest_ref varchar;
    v_rest_id varchar(12);
    v_rest_name text;
    v_rest_address text;
    v_town varchar(255);
    v_customer_name text;
    v_salt_number integer;
    v_rest_confirmation_code integer;
    v_created_at timestamp with time zone := CURRENT_TIMESTAMP;
    v_auto_accept boolean;
    v_pickup_minutes integer;
    v_pickup_time timestamp with time zone;
BEGIN
    v_rest_ref := COALESCE(p_rest_ref, SPLIT_PART(p_order_number, '-', 1));

    SELECT
        rm.rest_id,
        rm.rest_name,
        TRIM(CONCAT_WS(' ', rm.house_number, rm.building_name, rm.street_name, rm.city, rm.postcode)),
        rm.city INTO v_rest_id,
        v_rest_name,
        v_rest_address,
        v_town
    FROM
        restaurant_master rm
    WHERE
        rm.rest_ref = v_rest_ref;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Restaurant details not found for rest_ref: %', v_rest_ref;
    END IF;

    SELECT
        cm.cust_name INTO v_customer_name
    FROM
        customer_master cm
    WHERE
        cm.cust_id = p_cust_id;

    IF NOT FOUND OR v_customer_name IS NULL THEN
        v_customer_name := p_cust_id;
    END IF;

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

    v_rest_confirmation_code := floor(random() * (90 - (v_salt_number - 100) + 1) + (v_salt_number - 100))::int;

    SELECT
        acceptance.auto_accept,
        acceptance.pickup_minutes,
        acceptance.pickup_time INTO v_auto_accept,
        v_pickup_minutes,
        v_pickup_time
    FROM
        public.resolve_initial_restaurant_acceptance (v_rest_ref, 'takeaway', v_created_at) AS acceptance;

    RETURN QUERY INSERT INTO takeaway_summary (order_number, rest_id, rest_name, rest_address, town, customer_id, customer_name, restaurant_confirmation_status, restaurant_update_dtts, status, rest_confirmation_code, rest_prep_time_minutes, rest_confirmation_method, pickup_time, dtts)
        VALUES (p_order_number, v_rest_id, v_rest_name, v_rest_address, v_town, p_cust_id, v_customer_name, CASE WHEN v_auto_accept THEN
                'auto_accept'
            ELSE
                'restaurant_unconfirmed'
            END, CASE WHEN v_auto_accept THEN
                v_created_at
            ELSE
                NULL
            END, CASE WHEN v_auto_accept THEN
                'pickup_confirmed'
            ELSE
                'restaurant_unconfirmed'
            END, v_rest_confirmation_code, v_pickup_minutes, CASE WHEN v_auto_accept THEN
                'configured_auto'
            ELSE
                NULL
            END, v_pickup_time, v_created_at)
        -- Explicit list, qualified by table: RETURNING * breaks ("structure of query does not match function result type")
        -- the moment a column is added to takeaway_summary, and bare names clash with the RETURNS TABLE output variables.
    RETURNING
        takeaway_summary.order_number, takeaway_summary.rest_id, takeaway_summary.rest_name, takeaway_summary.rest_address, takeaway_summary.town, takeaway_summary.customer_id, takeaway_summary.customer_name, takeaway_summary.restaurant_confirmation_status, takeaway_summary.restaurant_update_dtts, takeaway_summary.restaurant_admin, takeaway_summary.status, takeaway_summary.rest_confirmation_code, takeaway_summary.rest_prep_time_minutes, takeaway_summary.rest_confirmation_method, takeaway_summary.restaurant_msg_id, takeaway_summary.customer_msg_id, takeaway_summary.pickup_time, takeaway_summary.pickup_date, takeaway_summary.rest_ref, takeaway_summary.dt, takeaway_summary.dtts;
END;
$$
LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.init_takeaway (p_cust_id character varying, p_order_number character varying, p_rest_ref character varying) IS 'Create the takeaway_summary row for an order and return it.';
