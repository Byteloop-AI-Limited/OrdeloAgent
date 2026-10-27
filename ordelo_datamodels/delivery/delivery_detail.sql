-- =============================================================================================
-- ordelo_datamodels/delivery/delivery_detail.sql
-- One row per delivery order and vehicle type being offered to riders (the dispatch 'option' currently open).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  delivery_detail
--                   Vehicle-type option of a delivery order (PK order_number + vehicle_type), with payout and distance.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
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
-- LIFECYCLE     status: unassigned -> assigned -> completed ; unassigned -> vehicle_type_timedout (no rider left for that vehicle).
-- CALLED BY     delivery_detail:
--                 sql       assign_accepted_dispatch(), cleanup_delivery_order(), complete_dispatch()
--                           delivery_dispatch_whook(), delivery_dispatch_whook_statement(), dispatch_accept_func()
--                           dispatch_cancel_before_pickup(), dispatch_complete_func(), init_delivery_detail()
--                           insert_delivery_detail(), job_assign_delivery(), job_assign_dispatch()
--                           job_create_dispatch(), manage_delivery_detail(), notify_missed_dispatches()
--                           notify_missed_dispatches_for_order(), process_delivery(), test_reset_order_and_dispatch()
--                 python    ordelo/agent_app_handlers.py: process_dispatch_response_from_rider_sync()
--                 python    ordelo/wa_location.py: WaLocation._load_delivery_context()
--                 python    utils_common/db_utils/sbase_realtime_ref.py: lifespan()
--                 python    watomation/routers/delivery_hooks.py: delivery_inflight_graph_init_hook()
-- PYTHON MODEL  ordelo_datamodels/delivery_pymodels.py DeliveryDetail
-- SECURITY      Proposed server-only grants below; public reads verified open 2026-10-26.
-- TESTS         tests/ordelo_datamodels/test_delivery_pymodels.py
--               tests/sql/test_restaurant_notices_script_sql.py
-- GOTCHAS       No foreign keys: the order_number links to delivery_summary by convention only.
-- SEE ALSO      delivery/process_delivery.sql
--               dispatch/job_create_dispatch.sql
--               dispatch/job_assign_dispatch.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table delivery_detail
--   Vehicle-type option of a delivery order (PK order_number + vehicle_type), with payout and distance.
--   process_delivery() inserts it; job_create_dispatch() offers it; assign_accepted_dispatch() sets rider_id/dispatch_id.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.delivery_detail (
    order_number character varying(100) NOT NULL,
    customer_id character varying(12) NOT NULL,
    vehicle_type character varying(15) NOT NULL,
    town character varying(255) NOT NULL,
    rider_payout double precision NOT NULL,
    distance double precision NOT NULL,
    status character varying(50) NOT NULL,
    dispatch_id integer,
    rider_id character varying(12),
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT delivery_detail_pkey1 PRIMARY KEY (order_number, vehicle_type),
    CONSTRAINT delivery_detail_status_check1 CHECK (((status)::text = ANY ((ARRAY['unassigned'::character varying, 'assigned'::character varying, 'vehicle_type_timedout'::character varying, 'completed'::character varying])::text[])))
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.delivery_detail IS 'Vehicle-type option of a delivery order (PK order_number + vehicle_type), with payout and distance.';

COMMENT ON COLUMN public.delivery_detail.status IS 'unassigned | assigned | vehicle_type_timedout | completed';

-- Private dashboard source: assignment details must not bypass the authenticated rider read.
ALTER TABLE public.delivery_detail ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.delivery_detail FROM PUBLIC, anon, authenticated;

GRANT ALL ON public.delivery_detail TO service_role;
