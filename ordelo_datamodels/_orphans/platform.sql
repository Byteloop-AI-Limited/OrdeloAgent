-- =============================================================================================
-- ordelo_datamodels/_orphans/platform.sql
-- Unused live test objects from early Supabase realtime experiments.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16). Orphan candidates: live, no caller found.
-- OBJECTS       table  sbase_test_realtime
--                   Test table for Supabase realtime (12 rows).
--               table  rec
--                   One-row scratch table.
--               fn     notify_http_endpoint() -> trigger
--                   Trigger function that POSTs old/new rows of sbase_test_realtime to a hard-coded live-track.byteloop.ai test URL.
--               trg    trigger_notify_http on sbase_test_realtime -> notify_http_endpoint()
--                   AFTER INSERT OR UPDATE ON sbase_test_realtime: runs notify_http_endpoint().
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none when applied. Functions that make HTTP calls or change rows only do so if someone calls them.
-- HOW IT FITS   Orphan candidates (Gate 1 decision D1): objects that exist on live but that nothing calls. A search on 2026-10-16 found
--                 no reference in OrdeloAgent, restaurant-frontend or restaurant-agents code, in any other live function or view, in a
--                 trigger or in a pg_cron job. They are captured here exactly as live so the repo describes the whole database.
--                 Nothing has been dropped: deciding keep or drop is an owner decision (docs/to-do.md). Before dropping one, re-check
--                 for callers outside these three repos (other services, manual scripts, Supabase Studio).
-- LIFECYCLE     none
-- CALLED BY     sbase_test_realtime:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
--               rec:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
--               notify_http_endpoint:
--                 trigger   trigger_notify_http on sbase_test_realtime
-- PYTHON MODEL  none
-- SECURITY      sbase_test_realtime: RLS OFF; Supabase default grants (anon and authenticated can read and write)
--               rec: RLS OFF; Supabase default grants (anon and authenticated can read and write)
--               notify_http_endpoint(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       trigger_notify_http is live and fires on every write to sbase_test_realtime (nothing writes to it).
-- SEE ALSO      docs/to-do.md (decide on orphan candidates)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table sbase_test_realtime
--   Test table for Supabase realtime (12 rows).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.sbase_test_realtime (
    id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
    column1 text NOT NULL,
    column2 text NOT NULL,
    CONSTRAINT sbase_test_realtime_pkey PRIMARY KEY (id)
);

-- ---------------------------------------------------------------------------------------------
-- table rec
--   One-row scratch table.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.rec (
    msg_id bigint,
    read_ct integer,
    enqueued_at timestamp with time zone,
    vt timestamp with time zone,
    message jsonb
);

-- ---------------------------------------------------------------------------------------------
-- function notify_http_endpoint() -> trigger
--   Trigger function that POSTs old/new rows of sbase_test_realtime to a hard-coded live-track.byteloop.ai test URL.
--   HTTP: POST (HTTP call, URL built at runtime)
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.notify_http_endpoint ()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $function$
DECLARE
    response json;
BEGIN
    -- Make the HTTP POST request to the specified endpoint
    response := (
        SELECT
            content
        FROM
            http_post ('https://live-track.byteloop.ai/test-sbase', json_build_object('old', row_to_json(OLD), 'new', row_to_json(NEW))::text, 'application/json'));
    -- Optionally, you can log the response or handle it as needed
    RAISE NOTICE 'Response from HTTP POST: %', response;

    RETURN NEW;
END;
$function$;

-- ---------------------------------------------------------------------------------------------
-- trigger trigger_notify_http on sbase_test_realtime -> notify_http_endpoint()
--   AFTER INSERT OR UPDATE ON sbase_test_realtime: runs notify_http_endpoint().
-- ---------------------------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trigger_notify_http ON public.sbase_test_realtime;

CREATE TRIGGER trigger_notify_http
    AFTER INSERT OR UPDATE ON sbase_test_realtime
    FOR EACH ROW
    EXECUTE FUNCTION notify_http_endpoint ();

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.sbase_test_realtime IS 'Test table for Supabase realtime (12 rows).';

COMMENT ON TABLE public.rec IS 'One-row scratch table.';

COMMENT ON FUNCTION public.notify_http_endpoint () IS 'Trigger function that POSTs old/new rows of sbase_test_realtime to a hard-coded live-track.byteloop.ai test URL.';

COMMENT ON TRIGGER trigger_notify_http ON public.sbase_test_realtime IS 'AFTER INSERT OR UPDATE ON sbase_test_realtime: runs notify_http_endpoint().';
