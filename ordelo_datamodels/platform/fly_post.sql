-- =============================================================================================
-- ordelo_datamodels/platform/fly_post.sql
-- Helper: start / stop / suspend a Fly.io machine through the Fly Machines API using the token in fly_config.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16), whose grants are wider than intended: see SECURITY.
-- OBJECTS       fn     fly_post(p_app_name text, p_action text) -> TABLE(status integer, content text)
--                   Call the Fly Machines API action for an app's machine using fly_config; returns the HTTP status and body.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call makes one HTTP request to the Fly Machines API (can stop production).
-- HOW IT FITS   SELECT * FROM fly_post('sfcs-agent', 'stop');   -- start | stop | suspend
--                 SECURITY DEFINER so callers never hold the token; needs the pgsql-http extension (search_path includes extensions).
--                 Run by hand or from a cron job; none is scheduled on 16 Oct 2026.
-- LIFECYCLE     none
-- CALLED BY     fly_post:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      fly_post(): executable by PUBLIC (default); SECURITY DEFINER
-- TESTS         none
-- GOTCHAS       URGENT (docs/to-do.md): the REVOKE below is commented because it is not live; anon can execute this function.
-- SEE ALSO      platform/fly_config.sql
--               docs/fly.io-deploy-guide.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function fly_post(p_app_name text, p_action text) -> TABLE(status integer, content text)
--   Call the Fly Machines API action for an app's machine using fly_config; returns the HTTP status and body.
--   Data: reads fly_config.
--   HTTP: POST /machines/
-- ---------------------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS fly_post (text, text);

CREATE OR REPLACE FUNCTION fly_post (p_app_name text, p_action text)
    RETURNS TABLE (
        status integer,
        content text)
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = public,
    extensions
    AS $$
DECLARE
    v_token text;
    v_machine_id text;
    v_url text;
    resp http_response;
BEGIN
    IF p_action NOT IN ('start', 'stop', 'suspend') THEN
        RAISE EXCEPTION 'Invalid action "%". Must be start | stop | suspend', p_action;
    END IF;

    SELECT
        api_token,
        machine_id INTO v_token,
        v_machine_id
    FROM
        fly_config
    WHERE
        app_name = p_app_name;

    IF v_token IS NULL OR v_machine_id IS NULL THEN
        RAISE EXCEPTION 'fly_config has no usable row for app "%"', p_app_name;
    END IF;

    v_url := 'https://api.machines.dev/v1/apps/' || p_app_name || '/machines/' || v_machine_id || '/' || p_action;
    -- Empty body, but pgsql-http requires a non-NULL `content` for POST, so pass ''
    -- (mirrors this repo's ordelo_post: http_post(url, '', 'application/json')).
    -- If Fly ever 400s on the empty JSON body, switch content from '' to '{}'.
    SELECT
        * INTO resp
    FROM
        http (('POST', v_url, ARRAY[http_header ('Authorization', 'Bearer ' || v_token)], 'application/json', -- content_type
    '' -- content: empty body (must be non-NULL for POST)
)::http_request);

    RETURN QUERY
    SELECT
        resp.status,
        resp.content::text;
END;
$$;

-- NOT APPLIED LIVE (2026-10-16): this REVOKE is the intended access rule, but the live function is still
-- executable by PUBLIC/anon/authenticated. Tracked in docs/to-do.md. Kept commented so this file matches live.
-- CRITICAL: a SECURITY DEFINER function in public is auto-exposed as a PostgREST RPC
-- and EXECUTE defaults to PUBLIC (anon/authenticated). Without this, anyone with the
-- anon key could stop prod, and the table RLS would NOT help (function reads as owner).
-- REVOKE EXECUTE ON FUNCTION fly_post(text, text) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION fly_post (text, text) TO service_role;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.fly_post (p_app_name text, p_action text) IS 'Call the Fly Machines API action for an app''s machine using fly_config; returns the HTTP status and body.';

-- -- Usage:
-- -- SELECT * FROM fly_post('sfcs-agent', 'stop');    -- nightly shutdown
-- -- SELECT * FROM fly_post('sfcs-agent', 'start');   -- morning boot
-- SELECT * FROM fly_post('sfcs-agent', 'stop');
-- SELECT * FROM fly_post('bnat-agent', 'stop');
