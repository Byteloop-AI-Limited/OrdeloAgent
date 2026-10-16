-- See also (paths under ordelo_datamodels/): takeaway_summary also carries ready_at and ready_by: added and explained in restaurant_admin/restaurant_ready_adjust_notices.sql. Accept/decline: restaurant_admin/restaurant_order_decision.sql.
-- Takeaway summary table and restaurant-confirmation webhook trigger.
CREATE TABLE IF NOT EXISTS public.takeaway_summary (
    order_number character varying(100) NOT NULL,
    rest_id character varying(12) NOT NULL,
    rest_name text NOT NULL,
    rest_address text NOT NULL,
    town character varying(255) NOT NULL,
    customer_id character varying(50) NOT NULL,
    customer_name text NOT NULL,
    restaurant_confirmation_status character varying(50) NOT NULL DEFAULT 'restaurant_unconfirmed' ::character varying,
    restaurant_update_dtts timestamp with time zone,
    restaurant_admin character varying(12),
    status character varying(50) NOT NULL,
    rest_confirmation_code integer NOT NULL,
    rest_prep_time_minutes integer,
    rest_confirmation_method character varying(20),
    restaurant_msg_id character varying(255),
    customer_msg_id character varying(255),
    pickup_time timestamp with time zone,
    pickup_date date NOT NULL DEFAULT CURRENT_DATE,
    rest_ref character varying(20) GENERATED ALWAYS AS (split_part((order_number)::text, '-'::text, 1)) STORED,
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ready_at timestamp with time zone, -- added by restaurant_admin/restaurant_ready_adjust_notices.sql
    ready_by text, -- added by restaurant_admin/restaurant_ready_adjust_notices.sql
    CONSTRAINT takeaway_summary_pkey PRIMARY KEY (order_number),
    CONSTRAINT takeaway_summary_restaurant_confirmation_status_check CHECK (((restaurant_confirmation_status)::text = ANY ((ARRAY['restaurant_unconfirmed'::character varying, 'restaurant_accept'::character varying, 'restaurant_decline'::character varying, 'restaurant_timedout'::character varying, 'auto_accept'::character varying, 'auto_decline'::character varying])::text[]))),
    CONSTRAINT takeaway_summary_status_check CHECK (((status)::text = ANY ((ARRAY['restaurant_unconfirmed'::character varying, 'pickup_confirmed'::character varying, 'declined'::character varying, 'completed'::character varying])::text[])))
);

CREATE INDEX IF NOT EXISTS idx_takeaway_summary_admin_day_local ON public.takeaway_summary USING btree (rest_ref, (((COALESCE(pickup_time, dtts) AT TIME ZONE 'Europe/London'::text))::date));

-- Same pair for takeaway_summary.
CREATE INDEX IF NOT EXISTS idx_takeaway_summary_admin_keyset ON public.takeaway_summary USING btree (rest_ref, COALESCE(pickup_time, dtts) DESC, order_number DESC);

/** description: takeaway_restaurant_updates_whook
 *  purpose: Sends a webhook request to the Ordelo app for takeaway restaurant confirmation workflow events
 *  parameters:
 *    - NEW: The new/updated takeaway_summary record
 *    - OLD: The old takeaway_summary record (for UPDATE operations)
 *  returns:
 *    - TRIGGER: The trigger object
 */
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

        IF NEW.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept', 'restaurant_decline', 'restaurant_timedout') THEN
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

DROP TRIGGER IF EXISTS trigger_takeaway_restaurant_updates ON public.takeaway_summary;

CREATE TRIGGER trigger_takeaway_restaurant_updates
    AFTER INSERT OR UPDATE OF restaurant_confirmation_status ON takeaway_summary
    FOR EACH ROW
    WHEN (new.restaurant_confirmation_status::text = ANY (ARRAY['restaurant_unconfirmed'::character varying, 'restaurant_accept'::character varying, 'restaurant_decline'::character varying, 'restaurant_timedout'::character varying]::text[]))
    EXECUTE FUNCTION takeaway_restaurant_updates_whook ();

/** description: takeaway_pickup_time_whook
 *  purpose: Sends a webhook when pickup_time is set (NULL → non-NULL) on takeaway_summary
 *  parameters:
 *    - NEW: The updated takeaway_summary record
 *    - OLD: The previous takeaway_summary record
 *  returns:
 *    - TRIGGER: The trigger object
 *  notes:
 *    - Fires only on UPDATE when OLD.pickup_time IS NULL AND NEW.pickup_time IS NOT NULL
 *    - Builds a lightweight payload with takeaway_summary + restaurant_master
 *    - POSTs to /takeaway-hooks/pickup-time-updated
 */
CREATE OR REPLACE FUNCTION takeaway_pickup_time_whook ()
    RETURNS TRIGGER
    AS $$
DECLARE
    webhook_payload json;
    ordelo_app_url text;
    webhook_url text;
    response json;
    takeaway_summary_json json;
    restaurant_master_json json;
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

    IF p_log_to_table THEN
        INSERT INTO debug_log (trigger_name, order_number, message)
            VALUES ('takeaway_pickup_time_whook', NEW.order_number, 'Trigger fired: pickup_time set from NULL to ' || NEW.pickup_time::text);
        END IF;
        -- Build takeaway_summary JSON from NEW record
        SELECT
            json_build_object('order_number', NEW.order_number, 'rest_id', NEW.rest_id, 'rest_name', NEW.rest_name, 'rest_address', NEW.rest_address, 'town', NEW.town, 'customer_id', NEW.customer_id, 'customer_name', NEW.customer_name, 'restaurant_confirmation_status', NEW.restaurant_confirmation_status, 'restaurant_update_dtts', NEW.restaurant_update_dtts, 'restaurant_admin', NEW.restaurant_admin, 'status', NEW.status, 'rest_confirmation_code', NEW.rest_confirmation_code, 'rest_prep_time_minutes', NEW.rest_prep_time_minutes, 'rest_confirmation_method', NEW.rest_confirmation_method, 'restaurant_msg_id', NEW.restaurant_msg_id, 'customer_msg_id', NEW.customer_msg_id, 'pickup_time', NEW.pickup_time, 'pickup_date', NEW.pickup_date, 'rest_ref', NEW.rest_ref, 'dt', NEW.dt, 'dtts', NEW.dtts) INTO takeaway_summary_json;
            -- Fetch restaurant_master data by rest_id
            SELECT
                json_build_object('rest_id', rm.rest_id, 'rest_ref', rm.rest_ref, 'rest_name', rm.rest_name, 'admins', rm.admins, 'lon', rm.lon, 'lat', rm.lat, 'house_number', rm.house_number, 'building_name', rm.building_name, 'street_name', rm.street_name, 'city', rm.city, 'postcode', rm.postcode) INTO restaurant_master_json
            FROM
                restaurant_master rm
            WHERE
                rm.rest_id = NEW.rest_id;
                -- Build complete webhook payload
                SELECT
                    json_build_object('takeaway_summary', takeaway_summary_json, 'restaurant_master', restaurant_master_json) INTO webhook_payload;
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

                            webhook_url := ordelo_app_url || '/takeaway-hooks/pickup-time-updated';

                            IF p_log_to_table THEN
                                INSERT INTO debug_log (trigger_name, order_number, message, payload)
                                    VALUES ('takeaway_pickup_time_whook', NEW.order_number, 'Posting webhook to ' || webhook_url, webhook_payload::jsonb);
                                END IF;

                                response := (
                                    SELECT
                                        content
                                    FROM
                                        http_post (webhook_url, webhook_payload::text, 'application/json'));

                                IF p_log_to_table THEN
                                    INSERT INTO debug_log (trigger_name, order_number, message, payload)
                                        VALUES ('takeaway_pickup_time_whook', NEW.order_number, 'HTTP response received', response::jsonb);
                                    END IF;

                                    RETURN NEW;
EXCEPTION
    WHEN OTHERS THEN
        IF p_log_to_table THEN
            INSERT INTO debug_log (trigger_name, order_number, message)
                VALUES ('takeaway_pickup_time_whook', NEW.order_number, 'ERROR: ' || SQLERRM);
            END IF;
            RAISE WARNING 'Error in takeaway_pickup_time_whook for order %: %', NEW.order_number, SQLERRM;
            RETURN NEW;
END;

$$
LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_takeaway_pickup_time_set ON public.takeaway_summary;

CREATE TRIGGER trigger_takeaway_pickup_time_set
    AFTER UPDATE OF pickup_time ON takeaway_summary
    FOR EACH ROW
    WHEN (old.pickup_time IS NULL AND new.pickup_time IS NOT NULL)
    EXECUTE FUNCTION takeaway_pickup_time_whook ();

-- Configured auto-accept sets pickup_time during INSERT, so it needs the
-- same pickup-finalized workflow without waiting for a follow-up UPDATE.
DROP TRIGGER IF EXISTS trigger_takeaway_pickup_time_insert ON public.takeaway_summary;

CREATE TRIGGER trigger_takeaway_pickup_time_insert
    AFTER INSERT ON takeaway_summary
    FOR EACH ROW
    WHEN (new.pickup_time IS NOT NULL)
    EXECUTE FUNCTION takeaway_pickup_time_whook ();
