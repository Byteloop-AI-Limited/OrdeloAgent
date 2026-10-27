-- =============================================================================================
-- ordelo_datamodels/delivery/delivery_summary.sql
-- One row per delivery order: restaurant, customer, confirmation state, delivery status, pickup time and kitchen state.
-- =============================================================================================
-- LIVE CHECK    Existing definitions retained; new dashboard access restrictions/revocation are not applied (2026-10-26).
-- OBJECTS       table  delivery_summary
--                   The delivery order as fulfilment sees it, one row per order_number (prefix = rest_ref).
--               trg    trigger_restaurant_updates on delivery_summary -> restaurant_updates_whook()
--                   AFTER INSERT OR UPDATE OF restaurant_confirmation_status, for the five statuses Python acts on.
--               trg    trigger_delivery_summary_timedout on delivery_summary -> delivery_summary_timedout_whook()
--                   AFTER UPDATE when status changes to 'timedout'.
--               fn     restaurant_updates_whook() -> trigger
--                   Trigger function: POST the order, restaurant, food_order and items to /delivery-hooks/restaurant-confirmation-request.
--               fn     delivery_summary_timedout_whook() -> trigger
--                   Trigger function: POST the summary row to /delivery-hooks/delivery-timedout when the order times out (no rider found).
--               fn     rider_pickup_alert_reschedule() -> trigger
--                   Trigger function: when pickup_time moves, re-time every rider_pickup_alert checkpoint of the order and set it back to 'pending'.
--               trg    trigger_pickup_time_reschedule on delivery_summary -> rider_pickup_alert_reschedule()
--                   AFTER UPDATE OF pickup_time when the value actually changes.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Applying the file re-creates three triggers. Each trigger POSTs to OrdeloAgent (see below) when it fires.
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
--                 Triggers on this table (defined below):
--                   trigger_restaurant_updates      restaurant_confirmation_status set/changed -> restaurant-confirmation-request webhook
--                   trigger_delivery_summary_timedout  status becomes 'timedout' -> delivery-timedout webhook
--                   trigger_pickup_time_reschedule  pickup_time changes -> re-time rider_pickup_alert checkpoints
--                 Admin dashboard indexes (idx_delivery_summary_admin_*) serve admin_dashboard/v_admin_orders.sql.
-- LIFECYCLE     status:  restaurant_unconfirmed -> unassigned -> assigned -> completed
--                        restaurant_unconfirmed -> declined                      (restaurant declined; never dispatched)
--                        unassigned -> timedout                                   (no rider for any vehicle type in time)
--               restaurant_confirmation_status:  restaurant_unconfirmed -> restaurant_accept | restaurant_decline | restaurant_timedout
--                        | auto_accept (configured) ; restaurant_accept -> restaurant_pickuptime_adjusted (+10 / +20)
--               Kitchen columns: ready_at / ready_by / ready_dispatch_id set by the first Ready tap per dispatch; pickup_time_initial /
--               pickup_adjusted_by / pickup_adjusted_at set by +10 / +20 (restaurant_admin/restaurant_ready_adjust_notices.sql).
-- CALLED BY     delivery_summary:
--                 sql       assign_accepted_dispatch(), cleanup_delivery_order(), delivery_dispatch_whook_statement()
--                           delivery_inflight_whook(), dispatch_cancel_before_pickup(), dispatch_complete_func()
--                           get_rider_payout_report(), handle_restaurant_confirmation(), init_delivery()
--                           job_payment_init_reconciler(), job_restaurant_confirmation_timeout()
--                           job_rider_pickup_alerts(), job_t_order_alerts(), overwatch_view(), process_delivery()
--                           process_restaurant_confirmation(), restaurant_order_adjust_pickup()
--                           restaurant_order_decide(), restaurant_order_ready(), restaurant_order_set_pickup()
--                           t_order_adjust_pickup(), t_order_card_row(), t_order_decide(), t_order_ready()
--                           t_order_set_pickup(), t_receipt_snapshot(), t_receipt_status()
--                           test_reset_order_and_dispatch(), v_admin_orders
--                 python    ordelo/agent_app_handlers.py: _send_delivery_instructions()
--                 python    ordelo/agents/agent_runner.py (module-level SQL)
--                 python    ordelo/agents/rider_agent.py: notify_pickup_reminder(), send_customer_contact(), send_dropoff_location(), send_pickup_location(), verify_customer_confirmation_code(), verify_restaurant_confirmation_code()
--                 python    ordelo/wa_location.py: WaLocation._load_delivery_context(), WaLocation.route_fulfilled_request()
--                 python    tgram_starter/order_card/state.py (module-level SQL)
--                 python    utils_common/notify/restaurant_notifier.py (module-level SQL)
--                 python    utils_common/order_management/restaurant_actions.py (module-level SQL)
--                 python    utils_common/order_management/restaurant_decision.py (module-level SQL)
--                 python    utils_common/web_ordering/customer_order_view.py: get_view()
--                 python    watomation/on_callback_wa_handler.py: admin_adjust_pickup_time(), dispatch_response()
--                 python    watomation/on_message_wa_handler.py: test_delivery()
--                 python    watomation/routers/delivery_hooks.py: DeliverySummaryData(), _handle_restaurant_decline(), _handle_restaurant_timedout(), check_rider_allocation_status(), delivery_inflight_graph_init_hook(), delivery_timedout(), post_rider_event_inflight(), restaurant_confirmation_flow()
--                 python    watomation/routers/location_hooks.py: notify_rider_location_event()
--                 python    watomation/routers/sys_admin_auth_session.py: get_rider_payout()
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/watomation/routers/rider_event_hooks.py
--                 r-agents  restaurant-agents/tests/legacy_contract/watomation/routers/test_rider_event_hooks.py
--                 r-agents  restaurant-agents/tests/watomation/test_specialist_lifecycle_updates.py
--               restaurant_updates_whook:
--                 trigger   trigger_restaurant_updates on delivery_summary
--               delivery_summary_timedout_whook:
--                 trigger   trigger_delivery_summary_timedout on delivery_summary
--               rider_pickup_alert_reschedule:
--                 trigger   trigger_pickup_time_reschedule on delivery_summary
-- PYTHON MODEL  ordelo_datamodels/delivery_pymodels.py DeliverySummary
-- SECURITY      Server-only grants and RLS below are proposed; live anonymous grants verified open 2026-10-26.
--               restaurant_updates_whook(): executable by PUBLIC (default)
--               delivery_summary_timedout_whook(): executable by PUBLIC (default)
--               rider_pickup_alert_reschedule(): executable by PUBLIC (default)
-- TESTS         tests/ordelo/agents/test_rider_agent.py
--               tests/ordelo/test_agent_app_handlers.py
--               tests/ordelo_datamodels/test_delivery_pymodels.py
--               tests/regressions/test_p5_regressions.py
--               tests/sql/test_order_cards_sql.py
--               tests/sql/test_order_taps_sql.py
--               tests/sql/test_order_test_script_sql.py
--               tests/sql/test_restaurant_decision_sql.py
--               tests/sql/test_restaurant_notices_script_sql.py
--               tests/sql/test_restaurant_ready_adjust_notices_sql.py
--               tests/test_sql_returning_star.py
--               tests/utils_common/test_restaurant_notifier.py
--               tests/utils_common/web_ordering/test_web_contract.py
--               tests/watomation/routers/test_delivery_hooks.py
--               tests/watomation/routers/test_location_hooks.py
--               tests/watomation/test_customer_notification_contracts.py
--               tests/watomation/test_on_callback_wa_handler.py
--               tests/watomation/test_on_message_wa_handler.py
-- GOTCHAS       Every webhook trigger swallows errors (RAISE WARNING) so an unreachable app never blocks the UPDATE: a missing
--                 prompt is diagnosed through debug_log (ENABLE_TRIGGER_DEBUG_LOG) and the Postgres log.
--               init_delivery() lists the RETURNING columns explicitly: never use RETURNING * there (tests/test_sql_returning_star.py).
--               rest_confirmation_code + cust_confirmation_code always add up to the CONFIRMATION_CODE_SALT number (init_delivery).
-- SEE ALSO      delivery/init_delivery.sql
--               delivery/process_delivery.sql
--               restaurant_admin/restaurant_order_decision.sql
--               restaurant_admin/restaurant_ready_adjust_notices.sql
--               dispatch/rider_pickup_alert.sql
--               docs/delivery_process.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table delivery_summary
--   The delivery order as fulfilment sees it, one row per order_number (prefix = rest_ref).
--   Copies restaurant and customer name/address/coordinates at creation; carries both confirmation codes, the
--   restaurant decision (restaurant_confirmation_status, restaurant_admin), the delivery status and the pickup time.
-- ---------------------------------------------------------------------------------------------
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
    ready_at timestamp with time zone, -- used by restaurant_admin/restaurant_ready_adjust_notices.sql
    ready_by text, -- admin phone (digits); label via restaurant_admin_label()
    -- used by restaurant_admin/restaurant_ready_adjust_notices.sql
    ready_dispatch_id integer, -- the dispatch the Ready was for (D35)
    -- used by restaurant_admin/restaurant_ready_adjust_notices.sql
    pickup_time_initial timestamp with time zone, -- pickup before the FIRST adjust (D32)
    -- used by restaurant_admin/restaurant_ready_adjust_notices.sql
    pickup_adjusted_by text, -- used by restaurant_admin/restaurant_ready_adjust_notices.sql
    pickup_adjusted_at timestamp with time zone, -- used by restaurant_admin/restaurant_ready_adjust_notices.sql
    CONSTRAINT delivery_summary_pkey PRIMARY KEY (order_number),
    CONSTRAINT delivery_summary_rest_confirmation_method_check CHECK (((rest_confirmation_method IS NULL) OR ((rest_confirmation_method)::text = ANY ((ARRAY['manual'::character varying, 'timeout'::character varying, 'configured_auto'::character varying])::text[])))),
    CONSTRAINT delivery_summary_restaurant_confirmation_status_check CHECK (((restaurant_confirmation_status)::text = ANY ((ARRAY['restaurant_unconfirmed'::character varying, 'restaurant_accept'::character varying, 'restaurant_decline'::character varying, 'restaurant_timedout'::character varying, 'auto_accept'::character varying, 'auto_decline'::character varying, 'restaurant_pickuptime_adjusted'::character varying])::text[]))),
    CONSTRAINT delivery_summary_status_check CHECK (((status)::text = ANY ((ARRAY['restaurant_unconfirmed'::character varying, 'unassigned'::character varying, 'timedout'::character varying, 'assigned'::character varying, 'completed'::character varying, 'declined'::character varying])::text[])))
);

-- Admin dashboard: London-local day, for WHERE rest_ref = $1 AND sort_day_local BETWEEN $2 AND $3.
CREATE INDEX IF NOT EXISTS idx_delivery_summary_admin_day_local ON public.delivery_summary USING btree (rest_ref, (((COALESCE(pickup_time, dtts) AT TIME ZONE 'Europe/London'::text))::date));

-- Admin dashboard (admin_dashboard/v_admin_orders.sql): keyset pagination per restaurant.
-- Supports WHERE rest_ref = $1 AND (sort_time, order_number) < (...) ORDER BY sort_time DESC, order_number DESC.
-- On a busy table create it with CREATE INDEX CONCURRENTLY, one statement at a time.
CREATE INDEX IF NOT EXISTS idx_delivery_summary_admin_keyset ON public.delivery_summary USING btree (rest_ref, COALESCE(pickup_time, dtts) DESC, order_number DESC);

-- ---------------------------------------------------------------------------------------------
-- trigger trigger_restaurant_updates on delivery_summary -> restaurant_updates_whook()
--   AFTER INSERT OR UPDATE OF restaurant_confirmation_status, for the five statuses Python acts on.
-- ---------------------------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trigger_restaurant_updates ON public.delivery_summary;

CREATE TRIGGER trigger_restaurant_updates
    AFTER INSERT OR UPDATE OF restaurant_confirmation_status ON delivery_summary
    FOR EACH ROW
    WHEN (new.restaurant_confirmation_status::text = ANY (ARRAY['restaurant_unconfirmed'::character varying, 'restaurant_accept'::character varying, 'restaurant_decline'::character varying, 'restaurant_timedout'::character varying, 'restaurant_pickuptime_adjusted'::character varying]::text[]))
    EXECUTE FUNCTION restaurant_updates_whook ();

-- ---------------------------------------------------------------------------------------------
-- trigger trigger_delivery_summary_timedout on delivery_summary -> delivery_summary_timedout_whook()
--   AFTER UPDATE when status changes to 'timedout'.
-- ---------------------------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trigger_delivery_summary_timedout ON public.delivery_summary;

CREATE TRIGGER trigger_delivery_summary_timedout
    AFTER UPDATE ON delivery_summary
    FOR EACH ROW
    WHEN (old.status::text <> 'timedout'::text AND new.status::text = 'timedout'::text)
    EXECUTE FUNCTION delivery_summary_timedout_whook ();

-- ---------------------------------------------------------------------------------------------
-- function restaurant_updates_whook() -> trigger
--   Trigger function: POST the order, restaurant, food_order and items to /delivery-hooks/restaurant-confirmation-request.
--   trigger_reason = the new restaurant_confirmation_status; Python (delivery_hooks.restaurant_confirmation_flow) sends
--   the admin prompt (unconfirmed), the pickup-time buttons (accept), the timeout default (timedout) or tells the rider
--   about an adjusted pickup (pickuptime_adjusted). Errors are logged, never raised.
--   Data: reads food_order, ordelo_config, order_item, restaurant_master; writes debug_log.
--   HTTP: POST /delivery-hooks/restaurant-confirmation-request -> watomation/routers/delivery_hooks.py::restaurant_confirmation_flow
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- function delivery_summary_timedout_whook() -> trigger
--   Trigger function: POST the summary row to /delivery-hooks/delivery-timedout when the order times out (no rider found).
--   Data: reads ordelo_config.
--   HTTP: POST /delivery-hooks/delivery-timedout -> watomation/routers/delivery_hooks.py::delivery_timedout
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- function rider_pickup_alert_reschedule() -> trigger
--   Trigger function: when pickup_time moves, re-time every rider_pickup_alert checkpoint of the order and set it back to 'pending'.
--   Catches every path that moves the time (admin +N buttons, the timeout default, manual SQL). A small move can repeat the
--   most recent reminder once; an 'awaiting_pickup' checkpoint reopened after pickup can never fire (phase gate).
--   Data: writes rider_pickup_alert.
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- trigger trigger_pickup_time_reschedule on delivery_summary -> rider_pickup_alert_reschedule()
--   AFTER UPDATE OF pickup_time when the value actually changes.
-- ---------------------------------------------------------------------------------------------
-- The first NULL -> value set fires this too, harmlessly: no rows exist yet.
DROP TRIGGER IF EXISTS trigger_pickup_time_reschedule ON public.delivery_summary;

CREATE TRIGGER trigger_pickup_time_reschedule
    AFTER UPDATE OF pickup_time ON delivery_summary
    FOR EACH ROW
    WHEN (new.pickup_time IS DISTINCT FROM old.pickup_time)
    EXECUTE FUNCTION rider_pickup_alert_reschedule ();

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.delivery_summary IS 'The delivery order as fulfilment sees it, one row per order_number (prefix = rest_ref).';

COMMENT ON TRIGGER trigger_restaurant_updates ON public.delivery_summary IS 'AFTER INSERT OR UPDATE OF restaurant_confirmation_status, for the five statuses Python acts on.';

COMMENT ON TRIGGER trigger_delivery_summary_timedout ON public.delivery_summary IS 'AFTER UPDATE when status changes to ''timedout''.';

COMMENT ON FUNCTION public.restaurant_updates_whook () IS 'Trigger function: POST the order, restaurant, food_order and items to /delivery-hooks/restaurant-confirmation-request.';

COMMENT ON FUNCTION public.delivery_summary_timedout_whook () IS 'Trigger function: POST the summary row to /delivery-hooks/delivery-timedout when the order times out (no rider found).';

COMMENT ON FUNCTION public.rider_pickup_alert_reschedule () IS 'Trigger function: when pickup_time moves, re-time every rider_pickup_alert checkpoint of the order and set it back to ''pending''.';

COMMENT ON TRIGGER trigger_pickup_time_reschedule ON public.delivery_summary IS 'AFTER UPDATE OF pickup_time when the value actually changes.';

COMMENT ON COLUMN public.delivery_summary.status IS 'Delivery lifecycle: restaurant_unconfirmed | unassigned | assigned | completed | timedout | declined';

COMMENT ON COLUMN public.delivery_summary.restaurant_confirmation_status IS 'Restaurant decision; every change fires trigger_restaurant_updates';

COMMENT ON COLUMN public.delivery_summary.pickup_time IS 'When the rider should collect; moving it re-times rider pickup alerts';

COMMENT ON COLUMN public.delivery_summary.ready_at IS 'First Ready tap for the current dispatch (restaurant_order_ready)';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- Set timeout for 30s
-- ALTER DATABASE postgres SET statement_timeout = '300s';

-- Private dashboard source: legitimate runtime callers use server credentials.
ALTER TABLE public.delivery_summary ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.delivery_summary FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.delivery_summary TO service_role;
