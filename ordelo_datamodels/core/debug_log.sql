-- =============================================================================================
-- ordelo_datamodels/core/debug_log.sql
-- Diagnostic log written by the restaurant-confirmation triggers when ENABLE_TRIGGER_DEBUG_LOG is on.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  debug_log
--                   Trigger diagnostics: trigger name, order number, message and optional payload.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none (DDL only)
-- HOW IT FITS   restaurant_updates_whook(), takeaway_restaurant_updates_whook() and takeaway_pickup_time_whook() insert a row per
--                 step (payload built, POST sent, error) when ordelo_config ENABLE_TRIGGER_DEBUG_LOG = 'true'. Nothing reads it
--                 automatically: it is for operators investigating a missing restaurant prompt.
-- LIFECYCLE     append-only; trim by hand when it grows.
-- CALLED BY     debug_log:
--                 sql       restaurant_confirmation_whook(), restaurant_updates_whook(), takeaway_pickup_time_whook()
--                           takeaway_restaurant_updates_whook()
-- PYTHON MODEL  none
-- SECURITY      debug_log: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         none
-- GOTCHAS       Grows without limit while the flag is on (about 14k rows on 16 Oct 2026).
-- SEE ALSO      delivery/delivery_summary.sql
--               takeaway/takeaway_summary.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table debug_log
--   Trigger diagnostics: trigger name, order number, message and optional payload.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.debug_log (
    id serial NOT NULL,
    trigger_name text,
    order_number text,
    message text,
    payload jsonb,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT debug_log_pkey PRIMARY KEY (id)
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.debug_log IS 'Trigger diagnostics: trigger name, order number, message and optional payload.';
