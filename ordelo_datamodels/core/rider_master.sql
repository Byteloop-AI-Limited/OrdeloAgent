-- =============================================================================================
-- ordelo_datamodels/core/rider_master.sql
-- One row per rider: phone (rider_id), vehicle, town, status and whether they are on shift.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  rider_master
--                   Riders that can be offered delivery jobs, keyed in practice by rider_id (their WhatsApp number).
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none (DDL only)
-- HOW IT FITS   get_available_riders() (dispatch/job_create_dispatch.sql) picks riders here: same town (case-insensitive), same
--                 vehicle_type, is_in_shift = true, not already offered this order and not on another job (delivery_inflight);
--                 TEST3100 orders only go to riders in ordelo_config overwatch_list. job_create_dispatch() then ranks by priority.
--                 Daily shift cycle: cron 'enquire_shift_availability' (11:00 UTC) -> enquire_shift_availability() POSTs the
--                 status = 'active' riders -> /delivery-hooks/shift-availability-enquiry sets is_in_shift = false for them and sends
--                 the shift question -> a 'yes' tap sets is_in_shift = true (watomation/on_callback_wa_handler.py).
--                 rider_id is the WhatsApp phone number and is what delivery_dispatch / delivery_inflight store.
-- LIFECYCLE     Riders are added by onboarding (rider_registrations -> manual insert into rider_master).
--               is_in_shift: reset to false every day by the shift enquiry, back to true when the rider answers yes.
-- CALLED BY     rider_master:
--                 sql       delivery_inflight_whook(), enquire_shift_availability(), fake_delivery_dispatch_whook()
--                           get_available_riders(), get_rider_payout_report(), job_rider_pickup_alerts()
--                           t_receipt_snapshot()
--                 python    utils_common/notify/restaurant_notifier.py (module-level SQL)
--                 python    utils_common/waba_utils/wa_senders.py: notify_ops_rider_alert(), notify_rest_admins_rider_alert()
--                 python    utils_common/web_ordering/customer_order_view.py: get_view()
--                 python    watomation/on_callback_wa_handler.py: handle_shift_availability()
--                 python    watomation/on_message_wa_handler.py: process_wa_msg()
--                 python    watomation/routers/delivery_hooks.py: delivery_inflight_graph_init_hook(), shift_availability_enquiry_hook()
--                 python    watomation/routers/rider_auth_session.py: _resolve_rider_id()
--                 python    watomation/routers/sys_admin_auth_session.py: get_rider_payout()
--                 frontend  restaurant-frontend/app/api/sys-admin/rider-payouts/summary/route.ts
--                 frontend  restaurant-frontend/app/rider/more/page.tsx
--                 frontend  restaurant-frontend/app/sys-admin/riders-inshift/page.tsx
-- PYTHON MODEL  none
-- SECURITY      rider_master: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         tests/regressions/test_p7_msg_handler.py
--               tests/sql/test_restaurant_notices_script_sql.py
--               tests/sql/test_restaurant_ready_adjust_notices_sql.py
--               tests/utils_common/test_restaurant_notifier.py
--               tests/watomation/routers/test_delivery_hooks.py
--               tests/watomation/test_on_message_wa_handler.py
-- GOTCHAS       rider_id is nullable and not unique in the DDL, although the code treats it as the rider's key.
--               Read with the anon key by restaurant-frontend and RLS is off: see docs/to-do.md (security review).
-- SEE ALSO      dispatch/job_create_dispatch.sql (get_available_riders)
--               dispatch/enquire_shift_availability.sql
--               core/rider_registrations.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table rider_master
--   Riders that can be offered delivery jobs, keyed in practice by rider_id (their WhatsApp number).
--   is_in_shift = true (plus matching town and vehicle) makes a rider dispatchable; status = 'active' decides who gets
--   the daily shift question; priority orders the offers (lower first); shift_response_dtts is the last shift update.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.rider_master (
    id serial NOT NULL,
    rider_id character varying(12),
    rider_name text NOT NULL,
    vehicle_type character varying(15) NOT NULL,
    town character varying(255) NOT NULL,
    status character varying(50) NOT NULL,
    is_in_shift boolean NOT NULL DEFAULT TRUE,
    priority integer NOT NULL DEFAULT 1,
    dtts timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    shift_response_dtts timestamp without time zone,
    CONSTRAINT rider_master_pkey PRIMARY KEY (id)
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.rider_master IS 'Riders that can be offered delivery jobs, keyed in practice by rider_id (their WhatsApp number).';

COMMENT ON COLUMN public.rider_master.is_in_shift IS 'true when the rider said they are working today; required for dispatch';
