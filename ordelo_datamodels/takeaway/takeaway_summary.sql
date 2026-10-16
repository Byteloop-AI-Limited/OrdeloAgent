-- =============================================================================================
-- ordelo_datamodels/takeaway/takeaway_summary.sql
-- One row per takeaway (collection) order: restaurant, customer, confirmation state, pickup time and Ready state.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  takeaway_summary
--                   The takeaway order as the restaurant sees it: customer, restaurant decision, pickup time and Ready state.
--               fn     takeaway_restaurant_updates_whook() -> trigger
--                   Trigger function: POST the order, restaurant, food_order and items to /takeaway-hooks/restaurant-confirmation-request (errors logged, never raised).
--               trg    trigger_takeaway_restaurant_updates on takeaway_summary -> takeaway_restaurant_updates_whook()
--                   AFTER INSERT OR UPDATE OF restaurant_confirmation_status (unconfirmed, accept, decline, timedout).
--               fn     takeaway_pickup_time_whook() -> trigger
--                   Trigger function: POST the order to /takeaway-hooks/pickup-time-updated so the customer is told when to collect.
--               trg    trigger_takeaway_pickup_time_set on takeaway_summary -> takeaway_pickup_time_whook()
--                   AFTER UPDATE OF pickup_time when it goes from NULL to a value.
--               trg    trigger_takeaway_pickup_time_insert on takeaway_summary -> takeaway_pickup_time_whook()
--                   AFTER INSERT when the row already has a pickup_time (configured auto-accept).
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Applying the file re-creates three triggers; each POSTs to OrdeloAgent when it fires.
-- HOW IT FITS   Takeaway (collection) order journey (takeaway_summary.status):
--                 1 create   /takeaway-hooks/init-takeaway-order -> init_takeaway(): 'restaurant_unconfirmed', or 'pickup_confirmed' with a
--                            pickup time when the restaurant auto-accepts.
--                 2 confirm  trigger_takeaway_restaurant_updates -> POST /takeaway-hooks/restaurant-confirmation-request -> admins asked.
--                            restaurant_order_decide() / restaurant_order_set_pickup() record the decision and pickup time
--                            ('pickup_confirmed'); process_restaurant_confirmation() (cron 10 s) times out unanswered orders.
--                 3 notify   pickup_time first set (or set at insert) -> trigger_takeaway_pickup_time_set / _insert ->
--                            POST /takeaway-hooks/pickup-time-updated -> customer told when to collect.
--                 4 ready    restaurant_order_ready() (WhatsApp or Telegram Ready) sets ready_at / ready_by; customer told.
-- LIFECYCLE     status: restaurant_unconfirmed -> pickup_confirmed -> completed ; restaurant_unconfirmed -> declined
--               restaurant_confirmation_status: restaurant_unconfirmed -> restaurant_accept | restaurant_decline | restaurant_timedout | auto_accept
-- CALLED BY     takeaway_summary:
--                 sql       init_takeaway(), job_payment_init_reconciler(), job_t_order_alerts()
--                           process_restaurant_confirmation(), restaurant_order_decide(), restaurant_order_ready()
--                           restaurant_order_set_pickup(), t_order_card_row(), t_order_decide(), t_order_ready()
--                           t_order_set_pickup(), t_receipt_snapshot(), t_receipt_status()
--                           test_reset_takeaway_order(), v_admin_orders
--                 python    utils_common/order_management/restaurant_actions.py (module-level SQL)
--                 python    utils_common/order_management/restaurant_decision.py (module-level SQL)
--                 python    utils_common/web_ordering/customer_order_view.py: get_view()
--                 python    watomation/routers/takeaway_hooks.py: TakeawaySummaryData(), _handle_restaurant_decline(), _handle_restaurant_timedout(), _post_pickup_time_event(), pickup_time_updated_hook()
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/services/order_management/takeaway_pymodels.py
--               takeaway_restaurant_updates_whook:
--                 trigger   trigger_takeaway_restaurant_updates on takeaway_summary
--               takeaway_pickup_time_whook:
--                 trigger   trigger_takeaway_pickup_time_insert on takeaway_summary
--                 trigger   trigger_takeaway_pickup_time_set on takeaway_summary
-- PYTHON MODEL  none
-- SECURITY      takeaway_summary: RLS OFF; Supabase default grants (anon and authenticated can read and write)
--               takeaway_restaurant_updates_whook(): executable by PUBLIC (default)
--               takeaway_pickup_time_whook(): executable by PUBLIC (default)
-- TESTS         tests/ordelo_datamodels/test_auto_accept_sql.py
--               tests/regressions/test_p7_takeaway.py
--               tests/sql/test_restaurant_notices_script_sql.py
--               tests/sql/test_restaurant_ready_adjust_notices_sql.py
--               tests/test_sql_returning_star.py
--               tests/utils_common/web_ordering/test_web_contract.py
--               tests/watomation/routers/test_takeaway_hooks.py
-- GOTCHAS       Nothing sets status 'completed' for takeaway yet (restaurant_admin/restaurant_ready_adjust_notices.sql NOT YET DONE).
--               Webhook triggers swallow errors (RAISE WARNING); check debug_log when a prompt is missing.
-- SEE ALSO      takeaway/init_takeaway.sql
--               restaurant_admin/restaurant_order_decision.sql
--               docs/takeaway_flow.md
--               docs/pickup_time_logic.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table takeaway_summary
--   The takeaway order as the restaurant sees it: customer, restaurant decision, pickup time and Ready state.
-- ---------------------------------------------------------------------------------------------
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
    ready_at timestamp with time zone, -- used by restaurant_admin/restaurant_ready_adjust_notices.sql
    ready_by text, -- used by restaurant_admin/restaurant_ready_adjust_notices.sql
    CONSTRAINT takeaway_summary_pkey PRIMARY KEY (order_number),
    CONSTRAINT takeaway_summary_restaurant_confirmation_status_check CHECK (((restaurant_confirmation_status)::text = ANY ((ARRAY['restaurant_unconfirmed'::character varying, 'restaurant_accept'::character varying, 'restaurant_decline'::character varying, 'restaurant_timedout'::character varying, 'auto_accept'::character varying, 'auto_decline'::character varying])::text[]))),
    CONSTRAINT takeaway_summary_status_check CHECK (((status)::text = ANY ((ARRAY['restaurant_unconfirmed'::character varying, 'pickup_confirmed'::character varying, 'declined'::character varying, 'completed'::character varying])::text[])))
);

-- Admin dashboard: London-local day filter.
CREATE INDEX IF NOT EXISTS idx_takeaway_summary_admin_day_local ON public.takeaway_summary USING btree (rest_ref, (((COALESCE(pickup_time, dtts) AT TIME ZONE 'Europe/London'::text))::date));

-- Admin dashboard (admin_dashboard/v_admin_orders.sql): keyset pagination per restaurant.
CREATE INDEX IF NOT EXISTS idx_takeaway_summary_admin_keyset ON public.takeaway_summary USING btree (rest_ref, COALESCE(pickup_time, dtts) DESC, order_number DESC);

-- ---------------------------------------------------------------------------------------------
-- function takeaway_restaurant_updates_whook() -> trigger
--   Trigger function: POST the order, restaurant, food_order and items to /takeaway-hooks/restaurant-confirmation-request (errors logged, never raised).
--   Data: reads food_order, ordelo_config, order_item, restaurant_master; writes debug_log.
--   HTTP: POST /takeaway-hooks/restaurant-confirmation-request -> watomation/routers/takeaway_hooks.py::restaurant_confirmation_flow
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- trigger trigger_takeaway_restaurant_updates on takeaway_summary -> takeaway_restaurant_updates_whook()
--   AFTER INSERT OR UPDATE OF restaurant_confirmation_status (unconfirmed, accept, decline, timedout).
-- ---------------------------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trigger_takeaway_restaurant_updates ON public.takeaway_summary;

CREATE TRIGGER trigger_takeaway_restaurant_updates
    AFTER INSERT OR UPDATE OF restaurant_confirmation_status ON takeaway_summary
    FOR EACH ROW
    WHEN (new.restaurant_confirmation_status::text = ANY (ARRAY['restaurant_unconfirmed'::character varying, 'restaurant_accept'::character varying, 'restaurant_decline'::character varying, 'restaurant_timedout'::character varying]::text[]))
    EXECUTE FUNCTION takeaway_restaurant_updates_whook ();

-- ---------------------------------------------------------------------------------------------
-- function takeaway_pickup_time_whook() -> trigger
--   Trigger function: POST the order to /takeaway-hooks/pickup-time-updated so the customer is told when to collect.
--   Data: reads ordelo_config, restaurant_master; writes debug_log.
--   HTTP: POST /takeaway-hooks/pickup-time-updated -> watomation/routers/takeaway_hooks.py::pickup_time_updated_hook
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- trigger trigger_takeaway_pickup_time_set on takeaway_summary -> takeaway_pickup_time_whook()
--   AFTER UPDATE OF pickup_time when it goes from NULL to a value.
-- ---------------------------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trigger_takeaway_pickup_time_set ON public.takeaway_summary;

CREATE TRIGGER trigger_takeaway_pickup_time_set
    AFTER UPDATE OF pickup_time ON takeaway_summary
    FOR EACH ROW
    WHEN (old.pickup_time IS NULL AND new.pickup_time IS NOT NULL)
    EXECUTE FUNCTION takeaway_pickup_time_whook ();

-- ---------------------------------------------------------------------------------------------
-- trigger trigger_takeaway_pickup_time_insert on takeaway_summary -> takeaway_pickup_time_whook()
--   AFTER INSERT when the row already has a pickup_time (configured auto-accept).
-- ---------------------------------------------------------------------------------------------
-- Configured auto-accept sets pickup_time during INSERT, so it needs the
-- same pickup-finalized workflow without waiting for a follow-up UPDATE.
DROP TRIGGER IF EXISTS trigger_takeaway_pickup_time_insert ON public.takeaway_summary;

CREATE TRIGGER trigger_takeaway_pickup_time_insert
    AFTER INSERT ON takeaway_summary
    FOR EACH ROW
    WHEN (new.pickup_time IS NOT NULL)
    EXECUTE FUNCTION takeaway_pickup_time_whook ();

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.takeaway_summary IS 'The takeaway order as the restaurant sees it: customer, restaurant decision, pickup time and Ready state.';

COMMENT ON FUNCTION public.takeaway_restaurant_updates_whook () IS 'Trigger function: POST the order, restaurant, food_order and items to /takeaway-hooks/restaurant-confirmation-request (errors logged, never raised).';

COMMENT ON TRIGGER trigger_takeaway_restaurant_updates ON public.takeaway_summary IS 'AFTER INSERT OR UPDATE OF restaurant_confirmation_status (unconfirmed, accept, decline, timedout).';

COMMENT ON FUNCTION public.takeaway_pickup_time_whook () IS 'Trigger function: POST the order to /takeaway-hooks/pickup-time-updated so the customer is told when to collect.';

COMMENT ON TRIGGER trigger_takeaway_pickup_time_set ON public.takeaway_summary IS 'AFTER UPDATE OF pickup_time when it goes from NULL to a value.';

COMMENT ON TRIGGER trigger_takeaway_pickup_time_insert ON public.takeaway_summary IS 'AFTER INSERT when the row already has a pickup_time (configured auto-accept).';

COMMENT ON COLUMN public.takeaway_summary.status IS 'restaurant_unconfirmed | pickup_confirmed | declined | completed';
