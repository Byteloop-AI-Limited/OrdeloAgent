-- =============================================================================================
-- ordelo_datamodels/delivery/init_delivery.sql
-- Create the delivery_summary row for a paid delivery order (step 1 of the delivery journey).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     init_delivery(p_cust_id character varying, p_order_number character varying, p_rest_ref character varying) -> TABLE(order_number character varying, rest_id character varying, rest_name text, rest_lon double precision, rest_lat double precision, rest_address text, town character varying, customer_id character varying, customer_name text, customer_lon double precision, customer_lat double precision, customer_address text, restaurant_confirmation_status character varying, restaurant_update_dtts timestamp with time zone, restaurant_admin character varying, status character varying, rest_confirmation_code integer, cust_confirmation_code integer, rest_prep_time_minutes integer, rest_confirmation_method character varying, restaurant_msg_id character varying, rider_msg_id character varying, customer_msg_id character varying, pickup_time timestamp with time zone, pickup_date date, rest_ref character varying, dt date, dtts timestamp with time zone, redispatch_dtts timestamp with time zone)
--                   Create the delivery_summary row for an order and return it.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call inserts one delivery_summary row, which fires trigger_restaurant_updates (restaurant prompt webhook).
-- HOW IT FITS   Delivery order journey (statuses in delivery_summary.status unless noted):
--                 1 create   /payment-hooks/payment-complete -> init_delivery() inserts the summary:
--                            'restaurant_unconfirmed', or 'unassigned' with a pickup time when the restaurant auto-accepts.
--                 2 confirm  trigger_restaurant_updates -> POST /delivery-hooks/restaurant-confirmation-request -> admins asked
--                            (WhatsApp buttons; Telegram cards via job_t_order_alerts). restaurant_order_decide() records accept /
--                            decline ('declined' is terminal); restaurant_order_set_pickup() sets pickup_time and 'unassigned'.
--                            process_restaurant_confirmation() (cron 10 s) marks unanswered orders 'restaurant_timedout'; Python then
--                            sets a default pickup time and 'unassigned'.
--                 3 options  process_delivery() (cron 5 s) adds delivery_detail rows, one vehicle type at a time by delivery_option rank,
--                            and marks the summary 'timedout' when every vehicle type timed out (trigger -> /delivery-hooks/delivery-timedout).
--                 4 offers   job_create_dispatch() (cron 5 s) inserts delivery_dispatch offers for available riders
--                            (trigger -> /delivery-hooks/delivery-dispatch -> WhatsApp offer to each rider).
--                 5 assign   a rider taps Accept (dispatch 'accepted'); job_assign_dispatch() (cron 5 s) gives the order to the first
--                            acceptance: dispatch/detail/summary 'assigned' + delivery_inflight row
--                            (trigger -> /delivery-hooks/delivery-inflight-graph-init starts the rider agent; other riders told they missed it).
--                 6 deliver  rider agent: pickup code check ('pickedup'), dispatch_cancel_before_pickup() re-offers the order,
--                            dispatch_complete_func() marks everything 'completed' and removes the inflight row.
--                 Around it: job_rider_pickup_alerts() reminders, kitchen Ready / +10 / +20 (restaurant_admin/), Telegram receipts.
-- LIFECYCLE     Creates the order in 'restaurant_unconfirmed', or in 'unassigned' with pickup_time and rest_confirmation_method
--               'configured_auto' when resolve_initial_restaurant_acceptance() says the restaurant auto-accepts.
-- CALLED BY     init_delivery:
--                 python    watomation/on_message_wa_handler.py: init_delivery_summary(), test_delivery()
--                 python    watomation/routers/payment_hooks.py: init_delivery_summary()
-- PYTHON MODEL  none
-- SECURITY      init_delivery(): executable by PUBLIC (default)
-- TESTS         tests/regressions/test_p7_msg_handler.py
--               tests/test_sql_returning_star.py
--               tests/utils_common/web_ordering/test_web_contract.py
-- GOTCHAS       Older notes said init_delivery 'eagerly calls process_delivery()'. It does not: the 5-second process_delivery cron job
--                 picks the order up.
--               RETURNING lists the columns: a RETURNING * breaks with SQLSTATE 42804 as soon as the table gains a column.
-- SEE ALSO      delivery/delivery_summary.sql
--               restaurant_admin/resolve_initial_restaurant_acceptance.sql
--               docs/delivery_process.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function init_delivery(p_cust_id character varying, p_order_number character varying, p_rest_ref character varying) -> TABLE(order_number character varying, rest_id character varying, rest_name text, rest_lon double precision, rest_lat double precision, rest_address text, town character varying, customer_id character varying, customer_name text, customer_lon double precision, customer_lat double precision, customer_address text, restaurant_confirmation_status character varying, restaurant_update_dtts timestamp with time zone, restaurant_admin character varying, status character varying, rest_confirmation_code integer, cust_confirmation_code integer, rest_prep_time_minutes integer, rest_confirmation_method character varying, restaurant_msg_id character varying, rider_msg_id character varying, customer_msg_id character varying, pickup_time timestamp with time zone, pickup_date date, rest_ref character varying, dt date, dtts timestamp with time zone, redispatch_dtts timestamp with time zone)
--   Create the delivery_summary row for an order and return it.
--   Reads the restaurant (restaurant_master; p_rest_ref, else the order-number prefix) and the customer (customer_master),
--   generates the restaurant/customer confirmation codes from ordelo_config CONFIRMATION_CODE_SALT (they add up to it),
--   and asks resolve_initial_restaurant_acceptance() whether to auto-accept. RAISEs if the restaurant, customer or salt is missing.
--   Called by /payment-hooks/payment-complete (payment_hooks.py) and the WhatsApp /test utility.
--   Data: reads customer_master, ordelo_config, restaurant_master; writes delivery_summary; calls resolve_initial_restaurant_acceptance().
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.init_delivery (p_cust_id character varying, p_order_number character varying, p_rest_ref character varying) IS 'Create the delivery_summary row for an order and return it.';
