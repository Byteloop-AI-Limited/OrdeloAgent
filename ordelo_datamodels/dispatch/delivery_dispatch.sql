-- =============================================================================================
-- ordelo_datamodels/dispatch/delivery_dispatch.sql
-- One row per job offer sent to a rider, with the rider's answer, payout and payment state.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     delivery_dispatch_whook_statement() -> trigger
--                   Statement trigger function: POST every offer inserted by one statement to /delivery-hooks/delivery-dispatch.
--               table  delivery_dispatch
--                   Offer of one delivery order to one rider (dispatch_id), with payout, distance, status and payout-paid state.
--               trg    trigger_delivery_dispatch_whook on delivery_dispatch -> delivery_dispatch_whook_statement()
--                   AFTER INSERT ... FOR EACH STATEMENT with REFERENCING NEW TABLE new_rows: one webhook per batch of offers.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Applying the file re-creates the statement trigger. Each INSERT statement then POSTs once to /delivery-hooks/delivery-dispatch.
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
--                 The statement-level trigger below batches every offer inserted by one job_create_dispatch() run into one
--                 POST /delivery-hooks/delivery-dispatch, which sends each rider a WhatsApp offer with Accept / Decline buttons.
--                 The rider dashboard and sys-admin payouts (restaurant-frontend) read paid_status / paid_dtts.
-- LIFECYCLE     delivery_dispatch.status (one row per offer of an order to one rider):
--                 unassigned (offer sent) -> accepted (rider tapped Accept) -> assigned (won the order) -> pickedup -> completed
--                 unassigned -> declined (rider said no, or cancelled before pickup) | missed (another rider won) | timedout
--               paid_status: unpaid -> paid (sys-admin marks payouts paid; paid_dtts set).
-- CALLED BY     delivery_dispatch_whook_statement:
--                 trigger   trigger_delivery_dispatch_whook on delivery_dispatch
--               delivery_dispatch:
--                 sql       assign_accepted_dispatch(), cleanup_delivery_order(), clear_dispatch()
--                           complete_dispatch(), dispatch_accept_func(), dispatch_cancel_before_pickup()
--                           dispatch_complete_func(), get_available_riders(), get_rider_payout_report()
--                           job_create_dispatch(), job_rider_pickup_alerts(), notify_missed_dispatches()
--                           notify_missed_dispatches_for_order(), overwatch_view(), restaurant_order_adjust_pickup()
--                           restaurant_order_ready(), t_receipt_snapshot(), t_receipt_status()
--                           test_reset_order_and_dispatch()
--                 python    ordelo/agent_app_handlers.py: _send_delivery_instructions(), initial_handle_of_rider_response(), process_dispatch_response_from_rider_sync()
--                 python    ordelo/agents/agent_runner.py: is_food_already_picked_up()
--                 python    ordelo/agents/rider_agent.py: capture_reason_for_cancel_before_pickup(), terminate_delivery_job(), verify_restaurant_confirmation_code()
--                 python    ordelo/delivery_progress.py: check_delivery_progress()
--                 python    ordelo/wa_location.py: WaLocation._load_delivery_context()
--                 python    utils_common/order_management/restaurant_actions.py (module-level SQL)
--                 python    utils_common/web_ordering/customer_order_view.py: get_view()
--                 python    watomation/routers/delivery_hooks.py: delivery_dispatch_hook(), notify_missed_dispatches_hook()
--                 python    watomation/routers/sys_admin_auth_session.py: get_rider_payout(), update_paid_status()
--                 frontend  restaurant-frontend/app/api/rider/jobs/route.ts
--                 frontend  restaurant-frontend/app/api/rider/jobs/summary/route.ts
--                 frontend  restaurant-frontend/app/api/sys-admin/rider-payouts/summary/route.ts
--                 frontend  restaurant-frontend/app/rider/jobs/_lib/server-fetcher.ts
-- PYTHON MODEL  ordelo_datamodels/delivery_pymodels.py DeliveryDispatch
-- SECURITY      delivery_dispatch_whook_statement(): executable by PUBLIC (default)
--               delivery_dispatch: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         tests/ordelo/agents/test_rider_agent.py
--               tests/ordelo/test_agent_app_handlers.py
--               tests/ordelo/test_delivery_progress.py
--               tests/ordelo_datamodels/test_delivery_pymodels.py
--               tests/sql/test_restaurant_notices_script_sql.py
--               tests/sql/test_restaurant_ready_adjust_notices_sql.py
--               tests/watomation/routers/test_delivery_hooks.py
--               tests/watomation/routers/test_sys_admin_auth_session.py
-- GOTCHAS       No foreign keys to delivery_summary or rider_master: the links are by order_number and rider_id only.
--               rider_pickup_alert has ON DELETE CASCADE to dispatch_id: deleting a dispatch (cancel before pickup) removes its alert ledger.
-- SEE ALSO      dispatch/job_create_dispatch.sql
--               dispatch/job_assign_dispatch.sql
--               dispatch/dispatch_cancel_before_pickup.sql
--               restaurant_admin/restaurant_ready_adjust_notices.sql (Ready reads the dispatch status)
--               docs/dispatch_flow.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function delivery_dispatch_whook_statement() -> trigger
--   Statement trigger function: POST every offer inserted by one statement to /delivery-hooks/delivery-dispatch.
--   Joins the inserted rows (new_rows) with delivery_detail and delivery_summary into one {"bulk_dispatch": [...]} payload.
--   Data: reads delivery_detail, delivery_summary, ordelo_config.
--   HTTP: POST /delivery-hooks/delivery-dispatch -> watomation/routers/delivery_hooks.py::delivery_dispatch_hook
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.delivery_dispatch_whook_statement ()
    RETURNS TRIGGER
    AS $$
DECLARE
    response json;
    webhook_payload json;
    app_url varchar;
    hook_url varchar;
BEGIN
    PERFORM
        set_config('statement_timeout', '10000', TRUE);
    -- Build payload by joining new_rows with delivery_detail in one query
    SELECT
        json_build_object('bulk_dispatch', json_agg(row_to_json(t))) INTO webhook_payload
    FROM (
        SELECT
            nr.dispatch_id,
            nr.order_number,
            nr.rider_id,
            nr.rider_payout,
            nr.vehicle_type,
            nr.distance,
            summ.pickup_time,
            summ.rest_id,
            summ.rest_name,
            summ.rest_lon,
            summ.rest_lat,
            summ.rest_address,
            summ.town,
            summ.customer_id,
            summ.customer_name,
            summ.customer_lon,
            summ.customer_lat,
            summ.customer_address
        FROM
            new_rows nr
            JOIN delivery_detail det ON nr.order_number = det.order_number
                AND det.vehicle_type = nr.vehicle_type
            JOIN delivery_summary summ ON summ.order_number = nr.order_number) t;
    -- Send single HTTP POST for all new rows
    SELECT
        config_value INTO app_url
    FROM
        ordelo_config
    WHERE
        config_key = 'ORDELO_APP_URL';

    IF app_url IS NULL OR length(app_url) = 0 THEN
        app_url := 'https://rider-agent.ordelo.app';
    END IF;
    -- Ensure no trailing slash before appending path
    IF
    RIGHT (app_url,
    1) = '/' THEN
        app_url :=
    LEFT (app_url,
        length(app_url) - 1);
    END IF;
    hook_url := app_url || '/delivery-hooks/delivery-dispatch';

    response := (
        SELECT
            content
        FROM
            http_post (hook_url, webhook_payload::text, 'application/json'));
    RAISE NOTICE 'Response from HTTP POST: %', response;

    RETURN NULL;
END;
$$
LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------
-- table delivery_dispatch
--   Offer of one delivery order to one rider (dispatch_id), with payout, distance, status and payout-paid state.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.delivery_dispatch (
    dispatch_id serial NOT NULL,
    order_number character varying(100) NOT NULL,
    rider_id character varying(12) NOT NULL,
    rider_payout double precision NOT NULL,
    vehicle_type character varying(15) NOT NULL,
    distance double precision NOT NULL,
    status character varying(50) NOT NULL,
    status_update_dtts timestamp without time zone,
    reason_for_decline text,
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    paid_status character varying(20) NOT NULL DEFAULT 'unpaid' ::character varying,
    paid_dtts timestamp without time zone,
    CONSTRAINT delivery_dispatch_pkey PRIMARY KEY (dispatch_id),
    CONSTRAINT delivery_dispatch_paid_status_check CHECK (((paid_status)::text = ANY ((ARRAY['unpaid'::character varying, 'paid'::character varying])::text[]))),
    CONSTRAINT delivery_dispatch_status_check CHECK (((status)::text = ANY ((ARRAY['unassigned'::character varying, 'timedout'::character varying, 'declined'::character varying, 'accepted'::character varying, 'missed'::character varying, 'assigned'::character varying, 'pickedup'::character varying, 'completed'::character varying])::text[])))
);

-- Rider dashboard: fast paid / unpaid listings per day.
CREATE INDEX IF NOT EXISTS delivery_dispatch_paid_status_dt_idx ON public.delivery_dispatch USING btree (paid_status, dt DESC);

-- ---------------------------------------------------------------------------------------------
-- trigger trigger_delivery_dispatch_whook on delivery_dispatch -> delivery_dispatch_whook_statement()
--   AFTER INSERT ... FOR EACH STATEMENT with REFERENCING NEW TABLE new_rows: one webhook per batch of offers.
-- ---------------------------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trigger_delivery_dispatch_whook ON public.delivery_dispatch;

CREATE TRIGGER trigger_delivery_dispatch_whook
    AFTER INSERT ON delivery_dispatch REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT
    EXECUTE FUNCTION delivery_dispatch_whook_statement ();

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.delivery_dispatch_whook_statement () IS 'Statement trigger function: POST every offer inserted by one statement to /delivery-hooks/delivery-dispatch.';

COMMENT ON TABLE public.delivery_dispatch IS 'Offer of one delivery order to one rider (dispatch_id), with payout, distance, status and payout-paid state.';

COMMENT ON TRIGGER trigger_delivery_dispatch_whook ON public.delivery_dispatch IS 'AFTER INSERT ... FOR EACH STATEMENT with REFERENCING NEW TABLE new_rows: one webhook per batch of offers.';

COMMENT ON COLUMN public.delivery_dispatch.status IS 'unassigned | accepted | assigned | pickedup | completed | declined | missed | timedout';

COMMENT ON COLUMN public.delivery_dispatch.paid_status IS 'Rider payout state: unpaid | paid';
