-- =============================================================================================
-- ordelo_datamodels/dispatch/delivery_inflight.sql
-- One row per delivery currently being carried out by a rider (assigned and not yet completed).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     delivery_inflight_whook() -> trigger
--                   Row trigger function: start the rider agent for a newly assigned job and tell the riders who missed it.
--               trg    trigger_delivery_inflight_whook on delivery_inflight -> delivery_inflight_whook()
--                   AFTER INSERT ON delivery_inflight FOR EACH ROW.
--               table  delivery_inflight
--                   Live job: dispatch_id (PK), order, rider and customer. Exists from assignment until completion or cancellation.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Applying the file re-creates the trigger; each INSERT POSTs to /delivery-hooks/delivery-inflight-graph-init.
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
--                 assign_accepted_dispatch() inserts the row; the trigger below then POSTs /delivery-hooks/delivery-inflight-graph-init
--                 (starts the rider LangGraph agent for this job) and calls notify_missed_dispatches() for the other riders.
--                 get_available_riders() treats any rider with an inflight row as busy. dispatch_complete_func() and
--                 dispatch_cancel_before_pickup() delete the row.
-- LIFECYCLE     inserted at assignment; deleted on completion or cancel before pickup (so the table only holds live jobs).
-- CALLED BY     delivery_inflight_whook:
--                 trigger   trigger_delivery_inflight_whook on delivery_inflight
--               delivery_inflight:
--                 sql       assign_accepted_dispatch(), cleanup_delivery_order(), complete_dispatch()
--                           dispatch_accept_func(), dispatch_cancel_before_pickup(), dispatch_complete_func()
--                           get_available_riders(), handle_delivery_dispatch_changes()
--                           job_null_or_outdated_location(), job_process_owntracks(), job_rider_pickup_alerts()
--                           restaurant_order_adjust_pickup(), restaurant_order_ready(), sync_delivery_inflight()
--                           t_receipt_snapshot(), t_receipt_status(), test_reset_order_and_dispatch()
--                 python    ordelo/agent_app_handlers.py: get_live_map_location_url()
--                 python    ordelo/agents/agent_runner.py: is_food_already_picked_up()
--                 python    ordelo/delivery_progress.py: check_delivery_progress()
--                 python    ordelo/wa_location.py: WaLocation._exact_inflight_assignment_exists_in_cursor()
--                 python    utils_common/notify/restaurant_notifier.py: KitchenReceipt()
--                 python    utils_common/order_management/restaurant_actions.py (module-level SQL)
--                 python    watomation/on_callback_wa_handler.py: dispatch_response(), handle_shift_availability()
--                 python    watomation/on_message_wa_handler.py: live_location(), reset_thread(), send_live_map_location()
--                 python    watomation/routers/delivery_hooks.py: delivery_inflight_graph_init_hook()
--                 python    ordelo/rider_shift.py: inflight_order() gates rider /off, /on and command menus
-- PYTHON MODEL  none
-- SECURITY      Proposed server-only grants below; public reads verified open 2026-10-26.
--               delivery_inflight: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         tests/ordelo/test_delivery_progress.py
--               tests/ordelo/test_wa_location.py
--               tests/regressions/test_p5_regressions.py
--               tests/regressions/test_p7_msg_handler.py
--               tests/sql/test_restaurant_notices_script_sql.py
--               tests/sql/test_restaurant_ready_adjust_notices_sql.py
--               tests/watomation/routers/test_delivery_hooks.py
--               tests/watomation/test_on_callback_wa_handler.py
--               tests/watomation/test_on_message_wa_handler.py
-- GOTCHAS       The Ready / +10 / +20 kitchen rule gates on this table: a delivery is 'in progress' while an inflight row exists and its
--                 dispatch is not 'pickedup' / 'completed' (restaurant_admin/restaurant_ready_adjust_notices.sql).
--               expire_wa_location_requests_on_inflight_delete (migrations/create_wa_location_tables.sql) is not live.
-- SEE ALSO      dispatch/job_assign_dispatch.sql
--               dispatch/notify_missed_dispatches.sql
--               rider_location/wa_location.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function delivery_inflight_whook() -> trigger
--   Row trigger function: start the rider agent for a newly assigned job and tell the riders who missed it.
--   POSTs the order summary and rider to /delivery-hooks/delivery-inflight-graph-init, then calls notify_missed_dispatches().
--   Data: reads delivery_summary, ordelo_config, rider_master; calls notify_missed_dispatches().
--   HTTP: POST /delivery-hooks/delivery-inflight-graph-init -> watomation/routers/delivery_hooks.py::delivery_inflight_graph_init_hook
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.delivery_inflight_whook ()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
DECLARE
    response json;
    webhook_payload json;
    notify_result boolean;
    app_url varchar;
    hook_url varchar;
BEGIN
    PERFORM
        set_config('statement_timeout', '10000', TRUE);
    -- Combine the NEW record with additional data from delivery_detail, delivery_summary, and rider_master; required to invoke graph
    SELECT
        json_build_object('delivery_inflight', json_build_array(row_to_json(NEW)), 'delivery_summary', (
                SELECT
                    row_to_json(summ)
                FROM delivery_summary summ
                WHERE
                    summ.order_number = NEW.order_number LIMIT 1), 'rider_master', (
                SELECT
                    row_to_json(rm)
                FROM (
                    SELECT
                        rider_name, rider_id
                    FROM rider_master
                WHERE
                    rider_id = NEW.rider_id LIMIT 1) rm)) INTO webhook_payload;
    -- Make the HTTP POST request with the combined payload
    SELECT
        config_value INTO app_url
    FROM
        ordelo_config
    WHERE
        config_key = 'ORDELO_APP_URL';

    IF app_url IS NULL OR length(app_url) = 0 THEN
        app_url := 'https://agent.ordelo.app';
    END IF;
    -- Ensure no trailing slash before appending path
    IF
    RIGHT (app_url,
    1) = '/' THEN
        app_url :=
    LEFT (app_url,
        length(app_url) - 1);
    END IF;
    hook_url := app_url || '/delivery-hooks/delivery-inflight-graph-init';

    response := (
        SELECT
            content
        FROM
            http_post (hook_url, webhook_payload::text, 'application/json'));
    -- Log the response
    RAISE NOTICE 'Response from HTTP POST to delivery-inflight-graph-init: %', response;
    -- Call notify_missed_dispatches_for_order with the order number
    SELECT
        notify_missed_dispatches () INTO notify_result;
    -- Log the result of notify_missed_dispatches_for_order
    RAISE NOTICE 'Result of notify_missed_dispatches for order %: %', NEW.order_number, notify_result;

    RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- trigger trigger_delivery_inflight_whook on delivery_inflight -> delivery_inflight_whook()
--   AFTER INSERT ON delivery_inflight FOR EACH ROW.
-- ---------------------------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trigger_delivery_inflight_whook ON public.delivery_inflight;

CREATE TRIGGER trigger_delivery_inflight_whook
    AFTER INSERT ON delivery_inflight
    FOR EACH ROW
    EXECUTE FUNCTION delivery_inflight_whook ();

-- ---------------------------------------------------------------------------------------------
-- table delivery_inflight
--   Live job: dispatch_id (PK), order, rider and customer. Exists from assignment until completion or cancellation.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.delivery_inflight (
    dispatch_id integer NOT NULL,
    order_number character varying(100) NOT NULL,
    rider_id character varying(12) NOT NULL,
    customer_id character varying(12) NOT NULL,
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT delivery_inflight_pkey PRIMARY KEY (dispatch_id)
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.delivery_inflight_whook () IS 'Row trigger function: start the rider agent for a newly assigned job and tell the riders who missed it.';

COMMENT ON TRIGGER trigger_delivery_inflight_whook ON public.delivery_inflight IS 'AFTER INSERT ON delivery_inflight FOR EACH ROW.';

COMMENT ON TABLE public.delivery_inflight IS 'Live job: dispatch_id (PK), order, rider and customer. Exists from assignment until completion or cancellation.';

-- Private dashboard source: assignment details must not bypass the authenticated rider read.
ALTER TABLE public.delivery_inflight ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.delivery_inflight FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.delivery_inflight TO service_role;
