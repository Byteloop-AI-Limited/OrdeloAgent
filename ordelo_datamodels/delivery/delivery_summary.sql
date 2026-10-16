-- See also (paths under ordelo_datamodels/): delivery_summary also carries the kitchen columns ready_at, ready_by, ready_dispatch_id, pickup_time_initial, pickup_adjusted_by, pickup_adjusted_at: added and explained in restaurant_admin/restaurant_ready_adjust_notices.sql. Accept/decline: restaurant_admin/restaurant_order_decision.sql.
-- drop table delivery_summary;
-- Add 'restaurant_pickuptime_adjusted' to restaurant_confirmation_status CHECK constraint
CREATE TABLE IF NOT EXISTS public.delivery_summary (
    order_number character varying(100) NOT NULL,
    rest_id character varying(12) NOT NULL, -- restaurant id
    rest_name text NOT NULL,
    rest_lon double precision NOT NULL,
    rest_lat double precision NOT NULL,
    rest_address text NOT NULL,
    town character varying(255) NOT NULL,
    customer_id character varying(50) NOT NULL, -- customer id
    customer_name text NOT NULL,
    customer_lon double precision NOT NULL,
    customer_lat double precision NOT NULL,
    customer_address text NOT NULL,
    -- Restaurant confirmation status (separate from delivery lifecycle)
    restaurant_confirmation_status character varying(50) NOT NULL DEFAULT 'restaurant_unconfirmed' ::character varying,
    restaurant_update_dtts timestamp with time zone, -- nullable, set when restaurant_confirmation_status changes
    restaurant_admin character varying(12), -- nullable, stores the admin phone who confirmed the order
    -- Delivery lifecycle status
    -- 'declined' added by restaurant_admin/restaurant_order_decision.sql (R1-a): a declined delivery is never dispatchable
    status character varying(50) NOT NULL,
    rest_confirmation_code integer NOT NULL,
    cust_confirmation_code integer NOT NULL,
    rest_prep_time_minutes integer, -- added by migrations/add_restaurant_confirmation_fields.sql
    rest_confirmation_method character varying(20), -- added by migrations/add_restaurant_confirmation_fields.sql
    -- WhatsApp message IDs for tracking communications
    restaurant_msg_id character varying(255), -- nullable, stores WA message ID for restaurant communications
    rider_msg_id character varying(255), -- nullable, stores WA message ID for rider communications
    customer_msg_id character varying(255), -- nullable, stores WA message ID for customer communications
    -- Scheduled pickup time selected by restaurant admins via `/PickupTime` callback.
    -- Downstream:
    -- 1) Included in webhook payload from restaurant_updates_whook()
    -- 2) Included later in rider dispatch payload/message
    -- 3) If NULL past timeout, process_restaurant_confirmation() moves flow to restaurant_timedout
    pickup_time timestamp with time zone,
    pickup_date date NOT NULL DEFAULT CURRENT_DATE,
    rest_ref character varying(20) GENERATED ALWAYS AS (split_part((order_number)::text, '-'::text, 1)) STORED, -- derived from order_number
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- "Current dispatch window started at" — populated only by
    -- dispatch_cancel_before_pickup on a successful pre-pickup decline.
    -- process_delivery uses COALESCE(redispatch_dtts, dtts) for the timeout
    -- base, so NULL means "no decline yet, use dtts".
    redispatch_dtts timestamp with time zone,
    ready_at timestamp with time zone, -- added by restaurant_admin/restaurant_ready_adjust_notices.sql
    ready_by text, -- admin phone (digits); label via restaurant_admin_label()
    -- added by restaurant_admin/restaurant_ready_adjust_notices.sql
    ready_dispatch_id integer, -- the dispatch the Ready was for (D35)
    -- added by restaurant_admin/restaurant_ready_adjust_notices.sql
    pickup_time_initial timestamp with time zone, -- pickup before the FIRST adjust (D32)
    -- added by restaurant_admin/restaurant_ready_adjust_notices.sql
    pickup_adjusted_by text, -- added by restaurant_admin/restaurant_ready_adjust_notices.sql
    pickup_adjusted_at timestamp with time zone, -- added by restaurant_admin/restaurant_ready_adjust_notices.sql
    CONSTRAINT delivery_summary_pkey PRIMARY KEY (order_number),
    CONSTRAINT delivery_summary_rest_confirmation_method_check CHECK (((rest_confirmation_method IS NULL) OR ((rest_confirmation_method)::text = ANY ((ARRAY['manual'::character varying, 'timeout'::character varying, 'configured_auto'::character varying])::text[])))),
    CONSTRAINT delivery_summary_restaurant_confirmation_status_check CHECK (((restaurant_confirmation_status)::text = ANY ((ARRAY['restaurant_unconfirmed'::character varying, 'restaurant_accept'::character varying, 'restaurant_decline'::character varying, 'restaurant_timedout'::character varying, 'auto_accept'::character varying, 'auto_decline'::character varying, 'restaurant_pickuptime_adjusted'::character varying])::text[]))),
    CONSTRAINT delivery_summary_status_check CHECK (((status)::text = ANY ((ARRAY['restaurant_unconfirmed'::character varying, 'unassigned'::character varying, 'timedout'::character varying, 'assigned'::character varying, 'completed'::character varying, 'declined'::character varying])::text[])))
);

-- Functional index on London-local day for date-range filtering.
-- Supports: WHERE rest_ref = $1 AND sort_day_local BETWEEN $2 AND $3
CREATE INDEX IF NOT EXISTS idx_delivery_summary_admin_day_local ON public.delivery_summary USING btree (rest_ref, (((COALESCE(pickup_time, dtts) AT TIME ZONE 'Europe/London'::text))::date));

-- Admin dashboard indexes
-- Apply these before admin_orders_views.sql.
-- In production, replace CREATE INDEX with CREATE INDEX CONCURRENTLY and run
-- each statement individually (CONCURRENTLY cannot run inside a transaction).

-- Keyset pagination + tenant filter on delivery_summary.
-- Supports: WHERE rest_ref = $1 AND (sort_time, order_number) < (...)
-- ORDER BY sort_time DESC, order_number DESC
CREATE INDEX IF NOT EXISTS idx_delivery_summary_admin_keyset ON public.delivery_summary USING btree (rest_ref, COALESCE(pickup_time, dtts) DESC, order_number DESC);

-- drop table delivery_summary;

-- Triggers on delivery_summary table
-- Trigger 1: On new record OR restaurant_confirmation_status update to 'restaurant_accept'/'restaurant_decline'/'restaurant_timedout'
-- This is the entry point for the restaurant-confirmation webhook chain:
-- delivery_summary change -> trigger_restaurant_updates -> restaurant_updates_whook()
-- -> POST /delivery-hooks/restaurant-confirmation-request -> restaurant_confirmation_flow()
-- -> _handle_restaurant_accept() when trigger_reason='restaurant_accept' (pickup-time options are sent)
DROP TRIGGER IF EXISTS trigger_restaurant_updates ON public.delivery_summary;

CREATE TRIGGER trigger_restaurant_updates
    AFTER INSERT OR UPDATE OF restaurant_confirmation_status ON delivery_summary
    FOR EACH ROW
    WHEN (new.restaurant_confirmation_status::text = ANY (ARRAY['restaurant_unconfirmed'::character varying, 'restaurant_accept'::character varying, 'restaurant_decline'::character varying, 'restaurant_timedout'::character varying, 'restaurant_pickuptime_adjusted'::character varying]::text[]))
    EXECUTE FUNCTION restaurant_updates_whook ();

-- drop trigger trigger_restaurant_updates on delivery_summary;

-- Trigger2: On status change to timeout
DROP TRIGGER IF EXISTS trigger_delivery_summary_timedout ON public.delivery_summary;

CREATE TRIGGER trigger_delivery_summary_timedout
    AFTER UPDATE ON delivery_summary
    FOR EACH ROW
    WHEN (old.status::text <> 'timedout'::text AND new.status::text = 'timedout'::text)
    EXECUTE FUNCTION delivery_summary_timedout_whook ();

-- Trigger Functions
/** description: restaurant_updates_whook
 *  purpose: Sends a webhook request to the Ordelo app for restaurant updates workflow events
 *  parameters: 
 *    - NEW: The new/updated delivery_summary record
 *    - OLD: The old delivery_summary record (for UPDATE operations)
 *  returns: 
 *    - TRIGGER: The trigger object
 *  notes:
 *    - Triggered on delivery_summary INSERT with restaurant_confirmation_status='restaurant_unconfirmed'
 *    - Triggered on delivery_summary UPDATE to restaurant_confirmation_status='restaurant_accept', 'restaurant_decline', 'restaurant_timedout', or 'restaurant_pickuptime_adjusted'
 *    - For trigger_reason='restaurant_accept', API handler _handle_restaurant_accept() sends pickup-time buttons
 *      and the selected value is written back to delivery_summary.pickup_time via /PickupTime callback
 *    - For trigger_reason='restaurant_timedout', API handler _handle_restaurant_timedout() auto-sets pickup_time (+30 mins)
 *    - For trigger_reason='restaurant_pickuptime_adjusted', set when an admin adjusts an already-set pickup_time
 *      (via /AdminAdjustPickupTime callback); API handler _handle_restaurant_pickuptime_adjusted() notifies the inflight rider
 *    - Builds delivery_summary JSON from NEW record (all fields)
 *    - Fetches restaurant_master data and includes in payload
 *    - Joins with food_order table using order_number
 *    - Fetches order items from order_item table
 *    - Includes trigger_reason field indicating the restaurant_confirmation_status that triggered the webhook
 *    - Constructs JSON matching RestaurantConfirmationPayload model (DeliverySummaryData + RestaurantMaster + FoodOrder + List[OrderItem])
 */
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
        -- Process for restaurant_unconfirmed, restaurant_accept, restaurant_decline, or restaurant_timedout
        IF NEW.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline', 'restaurant_timedout', 'restaurant_pickuptime_adjusted') THEN
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

-- Trigger 2:
/*
Delivery Summary Timedout Webhook Trigger
  . Fetches the base app URL from ordelo_config (key: ORDELO_APP_URL)
  . Constructs the webhook URL by appending '/delivery-hooks/delivery-timedout'
  . Constructs JSON payload from NEW record
  . Makes HTTP POST to the constructed webhook URL
  . Logs the response
  . Returns NEW for trigger continuation
Functions:
  . delivery_summary_timedout_whook
*/
CREATE OR REPLACE FUNCTION public.delivery_summary_timedout_whook ()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
DECLARE
    response json;
    webhook_payload json;
    ordelo_app_url text;
    webhook_url text;
BEGIN
    PERFORM
        set_config('statement_timeout', '10000', TRUE);
    -- Combine the NEW record with additional data from delivery_detail; required to invoke graph
    SELECT
        json_build_object('delivery_summary', json_build_array(row_to_json(NEW))) INTO webhook_payload;
    -- Fetch the base app URL from config, fallback to default if not present
    SELECT
        config_value INTO ordelo_app_url
    FROM
        ordelo_config
    WHERE
        config_key = 'ORDELO_APP_URL';
    IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
        ordelo_app_url := 'https://rider-agent.ordelo.app';
    END IF;
    webhook_url := ordelo_app_url || '/delivery-hooks/delivery-timedout';
    -- Make the HTTP POST request with the combined payload
    response := (
        SELECT
            content
        FROM
            http_post (webhook_url, webhook_payload::text, 'application/json'));
    -- Log the response
    RAISE NOTICE 'Response from HTTP POST to delivery-timedout: %', response;

    RETURN NEW;
END;
$$;

-- ===========================================================================
-- 5. RESCHEDULE -- keep the ledger honest when pickup_time moves
--    Any change to delivery_summary.pickup_time re-times and reopens every
--    checkpoint for that order.
-- ===========================================================================
-- One trigger covers all six buckets with no phase or audience logic, because
-- they all hang off the same anchor. It catches every path that moves the time:
-- the admin /AdminAdjustPickupTime button, the restaurant-timeout auto-set in
-- _handle_restaurant_timedout, and manual SQL.
--
-- It updates by order_number, which is safe only because the FK cascades: an
-- order cancelled pre-pickup and re-dispatched has lost its old
-- delivery_dispatch row, and the old ledger went with it.
--
-- Two consequences to expect while testing:
--   * A tiny adjustment reopens already-sent checkpoints, so the rider (and
--     ops) may get one repeat of the most recent one. Accepted -- they were
--     just told the time changed.
--   * An awaiting_pickup row still 'pending' when the rider collects is
--     reopened too, but can never fire again: the phase gate in (c) requires
--     dd.status = 'assigned' and the dispatch is now 'pickedup'.
CREATE OR REPLACE FUNCTION rider_pickup_alert_reschedule ()
    RETURNS TRIGGER
    AS $$
BEGIN
    UPDATE
        rider_pickup_alert a
    SET
        due_dtts = NEW.pickup_time + (a.offset_minutes * interval '1 minute'),
        status = 'pending',
        sent_dtts = NULL
    WHERE
        a.order_number = NEW.order_number;

    RETURN NEW;
END;
$$
LANGUAGE plpgsql;

-- The first NULL -> value set fires this too, harmlessly: no rows exist yet.
DROP TRIGGER IF EXISTS trigger_pickup_time_reschedule ON public.delivery_summary;

CREATE TRIGGER trigger_pickup_time_reschedule
    AFTER UPDATE OF pickup_time ON delivery_summary
    FOR EACH ROW
    WHEN (new.pickup_time IS DISTINCT FROM old.pickup_time)
    EXECUTE FUNCTION rider_pickup_alert_reschedule ();

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- Set timeout for 30s
-- ALTER DATABASE postgres SET statement_timeout = '300s';
