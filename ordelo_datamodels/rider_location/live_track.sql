-- =============================================================================================
-- ordelo_datamodels/rider_location/live_track.sql
-- Experimental live-tracking table ("live-track") written by utils_common/live_location/live_track_db_ops.py.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  live-track
--                   Device location samples (battery, lat/lon, topic, device and user ids) with range checks on lat/lon.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   utils_common/live_location/live_track_db_ops.py inserts device location rows here. The table has policies for the
--                 'authenticated' role, unlike the rest of the schema. It held no rows on 16 Oct 2026.
-- LIFECYCLE     none
-- CALLED BY     live-track:
--                 python    utils_common/live_location/live_track_db_ops.py: LiveTrackHandler.__init__()
-- PYTHON MODEL  none
-- SECURITY      live-track: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         none
-- GOTCHAS       The table name contains a hyphen, so it must always be quoted: public."live-track".
--               Captured from live on 2026-10-16; it had no file in the repo.
-- SEE ALSO      rider_location/rider_location.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table live-track
--   Device location samples (battery, lat/lon, topic, device and user ids) with range checks on lat/lon.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public."live-track" (
    id uuid NOT NULL DEFAULT uuid_generate_v4 (),
    battery integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    topic text NOT NULL,
    create_ts text NOT NULL,
    user_id text NOT NULL,
    device_id text NOT NULL,
    type text NOT NULL,
    connection text NOT NULL,
    CONSTRAINT "live-track_pkey" PRIMARY KEY (id),
    CONSTRAINT latitude_range CHECK (((latitude >= ('-90'::integer)::double precision) AND (latitude <= (90)::double precision))),
    CONSTRAINT longitude_range CHECK (((longitude >= ('-180'::integer)::double precision) AND (longitude <= (180)::double precision)))
);

CREATE INDEX IF NOT EXISTS idx_live_track_created_at ON public."live-track" USING btree (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_live_track_device ON public."live-track" USING btree (device_id);

CREATE INDEX IF NOT EXISTS idx_live_track_user ON public."live-track" USING btree (user_id);

DROP POLICY IF EXISTS "Allow authenticated read access" ON public."live-track";

CREATE POLICY "Allow authenticated read access" ON public."live-track" AS PERMISSIVE
    FOR SELECT TO authenticated
        USING (TRUE);

DROP POLICY IF EXISTS "Allow service insert" ON public."live-track";

CREATE POLICY "Allow service insert" ON public."live-track" AS PERMISSIVE
    FOR INSERT TO authenticated
        WITH CHECK (TRUE);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public."live-track" IS 'Device location samples (battery, lat/lon, topic, device and user ids) with range checks on lat/lon.';
