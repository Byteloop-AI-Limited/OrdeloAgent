-- =============================================================================================
-- ordelo_datamodels/dispatch/rider_pickup_alert.sql
-- Ledger of pickup / delivery reminder checkpoints per dispatch and audience (rider, ops, restaurant admins).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  rider_pickup_alert
--                   One checkpoint: (dispatch, phase awaiting_pickup|picked_up, audience rider|ops|rest_admins, offset minutes) with due and sent times.
-- REQUIRES      dispatch/delivery_dispatch.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   job_rider_pickup_alerts() seeds one row per checkpoint and marks it 'sent' / 'superseded'; the delivery_summary
--                 trigger rider_pickup_alert_reschedule() re-times rows when the pickup time moves. Full explanation, worked example
--                 and runbook: dispatch/job_rider_pickup_alerts.sql.
-- LIFECYCLE     status: pending -> sent | superseded (an older checkpoint overtaken by a later one); reopened to pending on reschedule.
-- CALLED BY     rider_pickup_alert:
--                 sql       job_rider_pickup_alerts(), rider_pickup_alert_reschedule()
-- PYTHON MODEL  none
-- SECURITY      rider_pickup_alert: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         tests/sql/test_restaurant_notices_script_sql.py
-- GOTCHAS       ON DELETE CASCADE from delivery_dispatch: a deleted dispatch takes its checkpoints with it.
-- SEE ALSO      dispatch/job_rider_pickup_alerts.sql
--               delivery/delivery_summary.sql (rider_pickup_alert_reschedule)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table rider_pickup_alert
--   One checkpoint: (dispatch, phase awaiting_pickup|picked_up, audience rider|ops|rest_admins, offset minutes) with due and sent times.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.rider_pickup_alert (
    dispatch_id integer NOT NULL,
    phase character varying(20) NOT NULL,
    audience character varying(20) NOT NULL,
    offset_minutes integer NOT NULL,
    order_number character varying(100) NOT NULL,
    rider_id character varying(12) NOT NULL,
    status character varying(20) NOT NULL DEFAULT 'pending' ::character varying,
    due_dtts timestamp with time zone NOT NULL,
    sent_dtts timestamp with time zone,
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT rider_pickup_alert_pkey PRIMARY KEY (dispatch_id, phase, audience, offset_minutes),
    CONSTRAINT rider_pickup_alert_audience_check CHECK (((audience)::text = ANY ((ARRAY['rider'::character varying, 'ops'::character varying, 'rest_admins'::character varying])::text[]))),
    CONSTRAINT rider_pickup_alert_phase_check CHECK (((phase)::text = ANY ((ARRAY['awaiting_pickup'::character varying, 'picked_up'::character varying])::text[]))),
    CONSTRAINT rider_pickup_alert_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'sent'::character varying, 'superseded'::character varying])::text[]))),
    CONSTRAINT rider_pickup_alert_dispatch_id_fkey FOREIGN KEY (dispatch_id) REFERENCES delivery_dispatch (dispatch_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS rider_pickup_alert_due_idx ON public.rider_pickup_alert USING btree (status, due_dtts);

CREATE INDEX IF NOT EXISTS rider_pickup_alert_order_idx ON public.rider_pickup_alert USING btree (order_number);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.rider_pickup_alert IS 'One checkpoint: (dispatch, phase awaiting_pickup|picked_up, audience rider|ops|rest_admins, offset minutes) with due and sent times.';

COMMENT ON COLUMN public.rider_pickup_alert.status IS 'pending | sent | superseded';
