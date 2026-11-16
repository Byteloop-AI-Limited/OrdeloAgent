-- MIGRATION (history; do not edit the statements below)
-- Applied to live: NOT YET (prepared 2026-11-16; the owner applies it himself)
-- Current definitions now live in: restaurant_admin/restaurant_confirmation_policy.sql, restaurant_admin/process_restaurant_confirmation.sql,
--          delivery/delivery_summary.sql, takeaway/takeaway_summary.sql, delivery/process_delivery.sql, telegram/t_order_alerts.sql
-- Purpose: restaurant confirmation timeout action (plans/restaurant-confirmation-timeout-action-plan.md).
--          {REF}_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION = 'decline' makes a never-answered order 'auto_decline' + status 'declined'
--          instead of being auto-accepted. One shared policy function; the rider-search clock now starts when the order became
--          dispatchable (affects every restaurant). No table, index or constraint change ('auto_decline' is already allowed).
--          Nothing changes for a restaurant with no action key, except the rider-search clock.
-- Requires: nothing else. Apply BEFORE deploying the code that calls restaurant_confirmation_policy().

/*
HOW TO APPLY (Supabase SQL editor, one block at a time, in this order; no BEGIN/COMMIT):

  STEP 0  PRE-CHECK (read only): expect false for the policy function before this migration.
  STEPS 1-7  Each block is CREATE OR REPLACE / DROP+CREATE and safe to re-run. Cron jobs keep running.
  STEP 8  VERIFY (read only): the queries at the bottom.
  STEP 9  python scripts/datamodels/drift_check.py
  STEP 10 Live test: test_restaurant_notices.sql STAGE 9 and STAGE 9b (both auto-accept while no action key exists).
  THEN    notebooks/db_queries/restaurant_queries/confirmation_timeout_action_rollout.sql (the config rows) when ready.
  ROLLBACK  The action rows are the switch: set them to 'accept' (instant). Restoring the old function bodies is only needed
            to undo the rider-clock change: re-run the previous git version of delivery/process_delivery.sql.
*/

-- STEP 0  PRE-CHECK (read only)
SELECT to_regprocedure('public.restaurant_confirmation_policy(text)') IS NOT NULL AS policy_exists_before;

-- STEP 1  Policy function (new, read only, safe to re-run)
CREATE OR REPLACE FUNCTION public.restaurant_confirmation_policy (p_rest_ref text, OUT timeout_minutes numeric, OUT timeout_action text)
    LANGUAGE sql
    STABLE
    AS $$
    SELECT
        COALESCE((
            SELECT
                config_value::numeric
            FROM
                public.ordelo_config
            WHERE
                config_key = p_rest_ref || '_RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1), (
            SELECT
                config_value::numeric
            FROM
                public.ordelo_config
            WHERE
                config_key = 'RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1), 5),
    CASE WHEN lower(btrim(COALESCE((
                SELECT
                    config_value
                FROM public.ordelo_config
                WHERE
                    config_key = p_rest_ref || '_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION' LIMIT 1), ''))) = 'decline' THEN
        'decline'
    ELSE
        'accept'
    END
$$;

COMMENT ON FUNCTION public.restaurant_confirmation_policy (text) IS 'Confirmation timeout policy for one restaurant: minutes to answer and what silence means (accept | decline).';

-- STEP 2  Timeout job (cron 'process_restaurant_confirmation' keeps running; its next run uses the new body)
CREATE OR REPLACE FUNCTION process_restaurant_confirmation ()
    RETURNS TABLE (
        action text)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY WITH delivery_timedout_confirmations AS (
        -- Delivery orders whose restaurant has not completed confirmation in time
    UPDATE
        delivery_summary ds
    SET
        -- Never answered and the restaurant declines on silence: terminal decline in this same UPDATE.
        -- Everything else (timeout action 'accept', or an admin accepted but chose no pickup time): as before.
        restaurant_confirmation_status = CASE WHEN ds.restaurant_confirmation_status = 'restaurant_unconfirmed'
            AND (public.restaurant_confirmation_policy (ds.rest_ref::text)).timeout_action = 'decline' THEN
            'auto_decline'
        ELSE
            'restaurant_timedout'
        END,
        status = CASE WHEN ds.restaurant_confirmation_status = 'restaurant_unconfirmed'
            AND (public.restaurant_confirmation_policy (ds.rest_ref::text)).timeout_action = 'decline' THEN
            'declined'
        ELSE
            ds.status
        END,
        restaurant_update_dtts = NOW()
    WHERE
        ds.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept')
        AND ds.pickup_time IS NULL
        AND (EXTRACT(EPOCH FROM (NOW() - ds.dtts)) / 60) > (public.restaurant_confirmation_policy (ds.rest_ref::text)).timeout_minutes
    RETURNING
        ds.order_number,
        ds.rest_ref,
        ds.restaurant_confirmation_status,
        'Delivery order ' || ds.order_number || ' (' || ds.rest_ref || ') → restaurant_confirmation_status set to ' || ds.restaurant_confirmation_status AS action
),
takeaway_timedout_confirmations AS (
    -- Takeaway orders whose restaurant has not completed confirmation in time
    UPDATE
        takeaway_summary ts
    SET
        -- Never answered and the restaurant declines on silence: terminal decline in this same UPDATE.
        -- Everything else (timeout action 'accept', or an admin accepted but chose no pickup time): as before.
        restaurant_confirmation_status = CASE WHEN ts.restaurant_confirmation_status = 'restaurant_unconfirmed'
            AND (public.restaurant_confirmation_policy (ts.rest_ref::text)).timeout_action = 'decline' THEN
            'auto_decline'
        ELSE
            'restaurant_timedout'
        END,
        status = CASE WHEN ts.restaurant_confirmation_status = 'restaurant_unconfirmed'
            AND (public.restaurant_confirmation_policy (ts.rest_ref::text)).timeout_action = 'decline' THEN
            'declined'
        ELSE
            ts.status
        END,
        restaurant_update_dtts = NOW()
    WHERE
        ts.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept')
        AND ts.pickup_time IS NULL
        AND (EXTRACT(EPOCH FROM (NOW() - ts.dtts)) / 60) > (public.restaurant_confirmation_policy (ts.rest_ref::text)).timeout_minutes
    RETURNING
        ts.order_number,
        ts.rest_ref,
        ts.restaurant_confirmation_status,
        'Takeaway order ' || ts.order_number || ' (' || ts.rest_ref || ') → restaurant_confirmation_status set to ' || ts.restaurant_confirmation_status AS action
)
SELECT
    dc.action
FROM
    delivery_timedout_confirmations dc
UNION ALL
SELECT
    tc.action
FROM
    takeaway_timedout_confirmations tc;
END;
$$;
--
-- STEP 3  Trigger function: let 'auto_decline' through (delivery)
CREATE OR REPLACE FUNCTION restaurant_updates_whook ()
    RETURNS TRIGGER
    AS $$
DECLARE
    webhook_payload json;
    ordelo_app_url text;
    webhook_url text;
    response json;
    delivery_summary_json json;
    restaurant_master_json json;
    food_order_json json;
    order_items_json json;
    food_order_id text;
    trigger_reason text;
    p_log_to_table boolean := TRUE;
    -- Default to TRUE, can be controlled via config
BEGIN
    PERFORM
        set_config('statement_timeout', '10000', TRUE);
    -- Check if logging is enabled (can be disabled via ordelo_config table)
    BEGIN
        SELECT
            COALESCE((config_value::boolean), TRUE) INTO p_log_to_table
        FROM
            ordelo_config
        WHERE
            config_key = 'ENABLE_TRIGGER_DEBUG_LOG';
    EXCEPTION
        WHEN OTHERS THEN
            p_log_to_table := TRUE;
            -- Default to TRUE if config not found
    END;
    -- Determine trigger reason from restaurant_confirmation_status
    trigger_reason := NEW.restaurant_confirmation_status;
    -- Log trigger fired
    IF p_log_to_table THEN
        INSERT INTO debug_log (trigger_name, order_number, message)
            VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Trigger fired, trigger_reason: ' || trigger_reason || ', TG_OP: ' || TG_OP);
        END IF;
        -- Process for restaurant_unconfirmed, restaurant_accept, restaurant_decline, restaurant_timedout, or auto_decline
        IF NEW.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline', 'restaurant_timedout', 'auto_decline', 'restaurant_pickuptime_adjusted') THEN
            IF p_log_to_table THEN
                INSERT INTO debug_log (trigger_name, order_number, message)
                    VALUES ('restaurant_confirmation_whook', NEW.order_number, 'restaurant_confirmation_status check passed - ' || NEW.restaurant_confirmation_status);
                END IF;
                -- Build delivery_summary JSON from NEW record (includes new columns)
                SELECT
                    json_build_object('order_number', NEW.order_number, 'rest_id', NEW.rest_id, 'rest_name', NEW.rest_name, 'rest_lon', NEW.rest_lon, 'rest_lat', NEW.rest_lat, 'rest_address', NEW.rest_address, 'town', NEW.town, 'customer_id', NEW.customer_id, 'customer_name', NEW.customer_name, 'customer_lon', NEW.customer_lon, 'customer_lat', NEW.customer_lat, 'customer_address', NEW.customer_address, 'restaurant_confirmation_status', NEW.restaurant_confirmation_status, 'restaurant_update_dtts', NEW.restaurant_update_dtts, 'restaurant_admin', NEW.restaurant_admin, 'status', NEW.status, 'rest_confirmation_code', NEW.rest_confirmation_code, 'cust_confirmation_code', NEW.cust_confirmation_code, 'rest_prep_time_minutes', NEW.rest_prep_time_minutes, 'rest_confirmation_method', NEW.rest_confirmation_method, 'restaurant_msg_id', NEW.restaurant_msg_id, 'rider_msg_id', NEW.rider_msg_id, 'customer_msg_id', NEW.customer_msg_id, 'pickup_time', NEW.pickup_time, 'pickup_date', NEW.pickup_date, 'rest_ref', NEW.rest_ref, 'dt', NEW.dt, 'dtts', NEW.dtts, 'redispatch_dtts', NEW.redispatch_dtts) INTO delivery_summary_json;
                    IF p_log_to_table THEN
                        INSERT INTO debug_log (trigger_name, order_number, message)
                            VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Delivery summary JSON built');
                        END IF;
                        -- Fetch restaurant_master data by rest_id and build JSON
                        SELECT
                            json_build_object('rest_id', rm.rest_id, 'rest_ref', rm.rest_ref, 'rest_name', rm.rest_name, 'admins', rm.admins, 'lon', rm.lon, 'lat', rm.lat, 'house_number', rm.house_number, 'building_name', rm.building_name, 'street_name', rm.street_name, 'city', rm.city, 'postcode', rm.postcode) INTO restaurant_master_json
                        FROM
                            restaurant_master rm
                        WHERE
                            rm.rest_id = NEW.rest_id;
                            IF p_log_to_table THEN
                                INSERT INTO debug_log (trigger_name, order_number, message)
                                    VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Restaurant master data fetched for rest_id: ' || NEW.rest_id);
                                END IF;
                                -- Fetch food_order data by order_number and build JSON
                                SELECT
                                    json_build_object('order_id', fo.order_id, 'order_number', fo.order_number, 'seq_id', fo.seq_id, 'recipient', fo.recipient, 'thread_id', fo.thread_id, 'action', fo.action, 'total_price', fo.total_price, 'final_order_value', fo.final_order_value, 'rest_cost', fo.rest_cost, 'service_charge', fo.service_charge, 'delivery_fee', fo.delivery_fee, 'small_order_fee', fo.small_order_fee, 'commission_rate', fo.commission_rate, 'payment_status', fo.payment_status),
                                    fo.order_id INTO food_order_json,
                                    food_order_id
                                FROM
                                    food_order fo
                                WHERE
                                    fo.order_number = NEW.order_number;
                                    -- Check if food_order was found
                                    IF food_order_json IS NULL THEN
                                        IF p_log_to_table THEN
                                            INSERT INTO debug_log (trigger_name, order_number, message)
                                                VALUES ('restaurant_confirmation_whook', NEW.order_number, 'WARNING: No food_order found for order_number');
                                            END IF;
                                            RAISE WARNING 'No food_order found for order_number %', NEW.order_number;
                                            RETURN NEW;
                                        END IF;
                                        IF p_log_to_table THEN
                                            INSERT INTO debug_log (trigger_name, order_number, message)
                                                VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Food order found: ' || food_order_id);
                                            END IF;
                                            -- Fetch order items for this order
                                            SELECT
                                                json_agg(json_build_object('order_id', oi.order_id, 'sku', oi.sku, 'quantity', oi.quantity, 'price', oi.price, 'product_name', oi.product_name)) INTO order_items_json
                                            FROM
                                                order_item oi
                                            WHERE
                                                oi.order_id = food_order_id;
                                                IF p_log_to_table THEN
                                                    INSERT INTO debug_log (trigger_name, order_number, message)
                                                        VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Order items fetched, count: ' || COALESCE(json_array_length(order_items_json), 0));
                                                    END IF;
                                                    -- Build complete webhook payload with all components
                                                    SELECT
                                                        json_build_object('trigger_reason', trigger_reason, 'delivery_summary', delivery_summary_json, 'restaurant_master', restaurant_master_json, 'food_order', food_order_json, 'order_items', COALESCE(order_items_json, '[]'::json)) INTO webhook_payload;
                                                        IF p_log_to_table THEN
                                                            INSERT INTO debug_log (trigger_name, order_number, message, payload)
                                                                VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Complete webhook payload built', webhook_payload::jsonb);
                                                            END IF;
                                                            -- Get webhook URL from config
                                                            SELECT
                                                                config_value INTO ordelo_app_url
                                                            FROM
                                                                ordelo_config
                                                            WHERE
                                                                config_key = 'ORDELO_APP_URL';
                                                                IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
                                                                    ordelo_app_url := 'https://rider-agent.ordelo.app';
                                                                    END IF;
                                                                    webhook_url := ordelo_app_url || '/delivery-hooks/restaurant-confirmation-request';
                                                                    IF p_log_to_table THEN
                                                                        INSERT INTO debug_log (trigger_name, order_number, message)
                                                                            VALUES ('restaurant_confirmation_whook', NEW.order_number, 'Webhook URL: ' || webhook_url);
                                                                        END IF;
                                                                        -- Make HTTP POST
                                                                        response := (
                                                                            SELECT
                                                                                content
                                                                            FROM
                                                                                http_post (webhook_url, webhook_payload::text, 'application/json'));
                                                                        IF p_log_to_table THEN
                                                                            INSERT INTO debug_log (trigger_name, order_number, message, payload)
                                                                                VALUES ('restaurant_confirmation_whook', NEW.order_number, 'HTTP response received', response::jsonb);
                                                                            END IF;
                                                                            RAISE NOTICE 'Restaurant confirmation request sent for order %: %', NEW.order_number, response;
                                                                        ELSE
                                                                            IF p_log_to_table THEN
                                                                                INSERT INTO debug_log (trigger_name, order_number, message)
                                                                                    VALUES ('restaurant_confirmation_whook', NEW.order_number, 'restaurant_confirmation_status check failed, current: ' || NEW.restaurant_confirmation_status);
                                                                                END IF;
            END IF;
            RETURN NEW;
EXCEPTION
    WHEN OTHERS THEN
        IF p_log_to_table THEN
            INSERT INTO debug_log (trigger_name, order_number, message)
                VALUES ('restaurant_confirmation_whook', NEW.order_number, 'ERROR: ' || SQLERRM);
            END IF;
            RAISE WARNING 'Error in restaurant_confirmation_whook for order %: %', NEW.order_number, SQLERRM;
            RETURN NEW;
END;

$$
LANGUAGE plpgsql;

-- STEP 4  Trigger function: let 'auto_decline' through (takeaway)
CREATE OR REPLACE FUNCTION takeaway_restaurant_updates_whook ()
    RETURNS TRIGGER
    AS $$
DECLARE
    webhook_payload json;
    ordelo_app_url text;
    webhook_url text;
    response json;
    takeaway_summary_json json;
    restaurant_master_json json;
    food_order_json json;
    order_items_json json;
    food_order_id text;
    trigger_reason text;
    p_log_to_table boolean := TRUE;
BEGIN
    PERFORM
        set_config('statement_timeout', '10000', TRUE);

    BEGIN
        SELECT
            COALESCE((config_value::boolean), TRUE) INTO p_log_to_table
        FROM
            ordelo_config
        WHERE
            config_key = 'ENABLE_TRIGGER_DEBUG_LOG';
    EXCEPTION
        WHEN OTHERS THEN
            p_log_to_table := TRUE;
    END;

    trigger_reason := NEW.restaurant_confirmation_status;

    IF p_log_to_table THEN
        INSERT INTO debug_log (trigger_name, order_number, message)
            VALUES ('takeaway_confirmation_whook', NEW.order_number, 'Trigger fired, trigger_reason: ' || trigger_reason || ', TG_OP: ' || TG_OP);
        END IF;

        IF NEW.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline', 'restaurant_timedout', 'auto_decline') THEN
            SELECT
                json_build_object('order_number', NEW.order_number, 'rest_id', NEW.rest_id, 'rest_name', NEW.rest_name, 'rest_address', NEW.rest_address, 'town', NEW.town, 'customer_id', NEW.customer_id, 'customer_name', NEW.customer_name, 'restaurant_confirmation_status', NEW.restaurant_confirmation_status, 'restaurant_update_dtts', NEW.restaurant_update_dtts, 'restaurant_admin', NEW.restaurant_admin, 'status', NEW.status, 'rest_confirmation_code', NEW.rest_confirmation_code, 'rest_prep_time_minutes', NEW.rest_prep_time_minutes, 'rest_confirmation_method', NEW.rest_confirmation_method, 'restaurant_msg_id', NEW.restaurant_msg_id, 'customer_msg_id', NEW.customer_msg_id, 'pickup_time', NEW.pickup_time, 'pickup_date', NEW.pickup_date, 'rest_ref', NEW.rest_ref, 'dt', NEW.dt, 'dtts', NEW.dtts) INTO takeaway_summary_json;

                IF p_log_to_table THEN
                    INSERT INTO debug_log (trigger_name, order_number, message)
                        VALUES ('takeaway_confirmation_whook', NEW.order_number, 'Takeaway summary JSON built');
                    END IF;

                    SELECT
                        json_build_object('rest_id', rm.rest_id, 'rest_ref', rm.rest_ref, 'rest_name', rm.rest_name, 'admins', rm.admins, 'lon', rm.lon, 'lat', rm.lat, 'house_number', rm.house_number, 'building_name', rm.building_name, 'street_name', rm.street_name, 'city', rm.city, 'postcode', rm.postcode) INTO restaurant_master_json
                    FROM
                        restaurant_master rm
                    WHERE
                        rm.rest_id = NEW.rest_id;

                        SELECT
                            json_build_object('order_id', fo.order_id, 'order_number', fo.order_number, 'seq_id', fo.seq_id, 'recipient', fo.recipient, 'thread_id', fo.thread_id, 'action', fo.action, 'total_price', fo.total_price, 'final_order_value', fo.final_order_value, 'rest_cost', fo.rest_cost, 'service_charge', fo.service_charge, 'delivery_fee', fo.delivery_fee, 'small_order_fee', fo.small_order_fee, 'commission_rate', fo.commission_rate, 'payment_status', fo.payment_status),
                            fo.order_id INTO food_order_json,
                            food_order_id
                        FROM
                            food_order fo
                        WHERE
                            fo.order_number = NEW.order_number;

                            IF food_order_json IS NULL THEN
                                IF p_log_to_table THEN
                                    INSERT INTO debug_log (trigger_name, order_number, message)
                                        VALUES ('takeaway_confirmation_whook', NEW.order_number, 'WARNING: No food_order found for order_number');
                                    END IF;
                                    RAISE WARNING 'No food_order found for order_number %', NEW.order_number;
                                    RETURN NEW;
                                END IF;

                                SELECT
                                    json_agg(json_build_object('order_id', oi.order_id, 'sku', oi.sku, 'quantity', oi.quantity, 'price', oi.price, 'product_name', oi.product_name)) INTO order_items_json
                                FROM
                                    order_item oi
                                WHERE
                                    oi.order_id = food_order_id;

                                    SELECT
                                        json_build_object('trigger_reason', trigger_reason, 'takeaway_summary', takeaway_summary_json, 'restaurant_master', restaurant_master_json, 'food_order', food_order_json, 'order_items', COALESCE(order_items_json, '[]'::json)) INTO webhook_payload;

                                        SELECT
                                            config_value INTO ordelo_app_url
                                        FROM
                                            ordelo_config
                                        WHERE
                                            config_key = 'ORDELO_APP_URL';

                                            IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
                                                ordelo_app_url := 'https://rider-agent.ordelo.app';
                                                END IF;

                                                webhook_url := ordelo_app_url || '/takeaway-hooks/restaurant-confirmation-request';

                                                IF p_log_to_table THEN
                                                    INSERT INTO debug_log (trigger_name, order_number, message, payload)
                                                        VALUES ('takeaway_confirmation_whook', NEW.order_number, 'Posting webhook to ' || webhook_url, webhook_payload::jsonb);
                                                    END IF;

                                                    response := (
                                                        SELECT
                                                            content
                                                        FROM
                                                            http_post (webhook_url, webhook_payload::text, 'application/json'));

                                                    IF p_log_to_table THEN
                                                        INSERT INTO debug_log (trigger_name, order_number, message, payload)
                                                            VALUES ('takeaway_confirmation_whook', NEW.order_number, 'HTTP response received', response::jsonb);
                                                        END IF;
            END IF;

            RETURN NEW;
EXCEPTION
    WHEN OTHERS THEN
        IF p_log_to_table THEN
            INSERT INTO debug_log (trigger_name, order_number, message)
                VALUES ('takeaway_confirmation_whook', NEW.order_number, 'ERROR: ' || SQLERRM);
            END IF;
            RAISE WARNING 'Error in takeaway_restaurant_updates_whook for order %: %', NEW.order_number, SQLERRM;
            RETURN NEW;
END;

$$
LANGUAGE plpgsql;

-- STEP 5  Triggers (delivery and takeaway)
DROP TRIGGER IF EXISTS trigger_restaurant_updates ON public.delivery_summary;

CREATE TRIGGER trigger_restaurant_updates
    AFTER INSERT OR UPDATE OF restaurant_confirmation_status ON delivery_summary
    FOR EACH ROW
    WHEN (new.restaurant_confirmation_status::text = ANY (ARRAY['restaurant_unconfirmed'::character varying, 'restaurant_accept'::character varying, 'restaurant_decline'::character varying, 'restaurant_timedout'::character varying, 'auto_decline'::character varying, 'restaurant_pickuptime_adjusted'::character varying]::text[]))
    EXECUTE FUNCTION restaurant_updates_whook ();

DROP TRIGGER IF EXISTS trigger_takeaway_restaurant_updates ON public.takeaway_summary;

CREATE TRIGGER trigger_takeaway_restaurant_updates
    AFTER INSERT OR UPDATE OF restaurant_confirmation_status ON takeaway_summary
    FOR EACH ROW
    WHEN (new.restaurant_confirmation_status::text = ANY (ARRAY['restaurant_unconfirmed'::character varying, 'restaurant_accept'::character varying, 'restaurant_decline'::character varying, 'restaurant_timedout'::character varying, 'auto_decline'::character varying]::text[]))
    EXECUTE FUNCTION takeaway_restaurant_updates_whook ();

-- STEP 6  Rider-search clock starts when the order became dispatchable
CREATE OR REPLACE FUNCTION process_delivery ()
    RETURNS TABLE (
        action text)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY WITH deliverySnapShot AS (
        SELECT
            summ.order_number,
            summ.customer_id,
            det.vehicle_type AS detail_vehicle_type,
            det.status AS detail_vehicle_status,
            dopt.rank AS available_vehicle_rank,
            dopt.vehicle_type AS available_vehicle_type,
            summ.town,
            dopt.driver_payout AS rider_payout,
            (dopt.breakdown::json ->> 'distance_miles')::double precision AS distance,
            rank() OVER (PARTITION BY summ.order_number ORDER BY det.status ASC NULLS FIRST,
                dopt.rank ASC) AS next_vehicle_rank
        FROM
            delivery_summary summ
            JOIN delivery_option dopt ON dopt.order_number = summ.order_number
            LEFT JOIN delivery_detail det ON det.order_number = summ.order_number
                AND det.vehicle_type = dopt.vehicle_type
        WHERE
            summ.status = 'unassigned'
),
timedout_orders AS (
    -- which orders have *all* vehicles timed-out?
    SELECT
        order_number
    FROM
        deliverySnapShot
    GROUP BY
        order_number
    HAVING
        MAX(available_vehicle_rank) = SUM((detail_vehicle_status = 'vehicle_type_timedout')::int)
),
update_summary AS (
    -- mark those orders as timed-out using restaurant-specific or default timeout
    UPDATE
        delivery_summary ds
    SET
        status = 'timedout'
    FROM
        timedout_orders t
    WHERE
        ds.order_number = t.order_number
        AND ds.status = 'unassigned'
        -- The rider-search clock starts when the order became dispatchable: redispatch_dtts when present (set by
        -- dispatch_cancel_before_pickup on a pre-pickup decline), else restaurant_update_dtts (the restaurant's pickup-time
        -- choice, or the confirmation timeout; set at creation for configured auto-accept), else dtts (order creation).
        -- The time the restaurant took to answer is therefore not taken from the riders' window.
        AND (EXTRACT(EPOCH FROM (NOW() - COALESCE(ds.redispatch_dtts, ds.restaurant_update_dtts, ds.dtts))) / 60) > COALESCE((
            SELECT
                config_value::int
            FROM ordelo_config
            WHERE
                config_key = ds.rest_ref || '_DELIVERY_TIMEOUT_TIME' LIMIT 1), (
            SELECT
                config_value::int
            FROM ordelo_config
            WHERE
                config_key = 'DELIVERY_TIMEOUT_TIME' LIMIT 1), 10 -- fallback to 10 minutes if no config found
)
    RETURNING
        'Order ' || ds.order_number || ' → status set to timeout' AS action
),
to_insert AS (
    -- which un‐assigned orders where all existing details are timed-out
    SELECT
        order_number,
        customer_id,
        available_vehicle_type,
        town,
        rider_payout,
        distance
    FROM
        deliverySnapShot ds_outer
    WHERE
        ds_outer.next_vehicle_rank = 1
        AND ds_outer.detail_vehicle_status IS NULL
        AND NOT EXISTS (
            SELECT
                1
            FROM
                deliverySnapShot ds2
            WHERE
                ds2.order_number = ds_outer.order_number
                AND ds2.detail_vehicle_status IS NOT NULL
                AND ds2.detail_vehicle_status <> 'vehicle_type_timedout')
),
insert_details AS (
    -- insert exactly that “next” vehicle as a new detail row
    INSERT INTO delivery_detail (order_number, customer_id, vehicle_type, town, rider_payout, distance, status)
    SELECT
        order_number,
        customer_id,
        available_vehicle_type,
        town,
        rider_payout,
        distance,
        'unassigned'
    FROM
        to_insert
    RETURNING
        'Order ' || order_number || ' → inserted detail for vehicle_type ' || vehicle_type AS action)
-- finally stitch the two logs together
SELECT
    us.action
FROM
    update_summary us
UNION ALL
SELECT
    id.action
FROM
    insert_details id;
END;
$$;

-- STEP 7  Telegram card status 'auto_declined'
CREATE OR REPLACE FUNCTION public.t_order_card_status (p_rcs text, p_pickup timestamptz)
    RETURNS text
    LANGUAGE sql
    IMMUTABLE
    AS $$
    SELECT
        CASE WHEN p_rcs IS NULL THEN
            NULL
        WHEN p_rcs = 'restaurant_unconfirmed' THEN
            'awaiting'
        WHEN p_rcs = 'restaurant_decline' THEN
            'declined'
        WHEN p_rcs = 'auto_decline' THEN
            'auto_declined'
        WHEN p_rcs IN ('restaurant_accept', 'restaurant_pickuptime_adjusted') THEN
            CASE WHEN p_pickup IS NULL THEN
                'accepted'
            ELSE
                'pickup_set'
        END
        WHEN p_rcs IN ('auto_accept', 'restaurant_timedout') THEN
            CASE WHEN p_pickup IS NULL THEN
                'awaiting'
            ELSE
                'auto_accepted'
        END
        ELSE
            'awaiting'
        END
$$;

-- STEP 8  VERIFY (read only). Expect 5 / accept for a restaurant with no keys.
SELECT * FROM public.restaurant_confirmation_policy ('ZZZZ');
