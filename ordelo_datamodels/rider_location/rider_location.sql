-- =============================================================================================
-- ordelo_datamodels/rider_location/rider_location.sql
-- Rider GPS fixes from OwnTracks, one row per message.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  rider_location
--                   One OwnTracks location fix: rider, optional customer/order, lat/lon, accuracy, battery and device timestamp (tst).
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   Continuous rider tracking (OwnTracks app on the rider's phone):
--                 OwnTracks -> HTTP endpoint -> pgmq queue 'owntracks' (schema pgmq)
--                 cron 'job_process_owntracks' (30 s) -> job_process_owntracks():
--                     location messages  -> rider_location (one row per GPS fix, linked to the rider's live order if any)
--                     transition events  -> rider_location_event (enter / leave a region)
--                                           -> trigger -> POST /location-hooks/notify-rider-location-event (customer / restaurant updates)
--                 The customer's live map (/location-hooks/live-location-map/{order}) reads rider_location.
--                 job_null_or_outdated_location() (cron, INACTIVE) would alert about live jobs whose rider sent no recent fix.
-- LIFECYCLE     append-only; nothing trims it (about 21k rows on 16 Oct 2026, last write in April 2026).
-- CALLED BY     rider_location:
--                 sql       job_null_or_outdated_location(), job_process_owntracks()
--                 python    ordelo/agent_app_handlers.py: get_live_map_location_url(), is_live_location_enabled()
--                 python    watomation/on_message_wa_handler.py: live_location()
--                 python    watomation/routers/location_hooks.py: process_location_transitionTBD()
-- PYTHON MODEL  none
-- SECURITY      rider_location: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         tests/ordelo/test_agent_app_handlers.py
-- GOTCHAS       The two indexes in the commented examples (tst DESC, dtts DESC) were never created live: docs/to-do.md.
--               No primary key.
-- SEE ALSO      rider_location/job_process_owntracks.sql
--               rider_location/rider_location_event.sql
--               docs/location_overview.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table rider_location
--   One OwnTracks location fix: rider, optional customer/order, lat/lon, accuracy, battery and device timestamp (tst).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.rider_location (
    topic character varying(255),
    rider_id character varying(12),
    customer_id character varying(12),
    order_number character varying(100),
    acc integer,
    alt integer,
    batt integer,
    lat double precision NOT NULL,
    lon double precision NOT NULL,
    tst integer,
    tid character varying(255),
    conn character varying(1),
    inregions text[],
    inrids text[],
    created_at integer,
    m integer,
    tst_dtts timestamp without time zone,
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.rider_location IS 'One OwnTracks location fix: rider, optional customer/order, lat/lon, accuracy, battery and device timestamp (tst).';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- drop table
-- CREATE INDEX IF NOT EXISTS idx_rider_location_tst_desc ON rider_location (tst DESC);

-- CREATE INDEX IF NOT EXISTS idx_rider_location_dtts_desc ON rider_location (dtts DESC);
