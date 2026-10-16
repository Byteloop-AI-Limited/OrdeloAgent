-- ============================================================
-- Helper: POST a lifecycle action to the Fly Machines REST API.
-- Reads the app-scoped token + machine id from fly_config (SECURITY DEFINER),
-- so callers never hold the token. Actions map 1:1 to the Fly endpoint path.
-- Usage: SELECT * FROM fly_post('sfcs-agent', 'stop');   -- start | stop | suspend
--
-- Requires the pgsql-http extension (http/http_header/http_request/http_response).
-- On Supabase that extension lives in the `extensions` schema, hence the search_path
-- below. Verify with:
--   SELECT extnamespace::regnamespace FROM pg_extension WHERE extname = 'http';
-- ============================================================
DROP FUNCTION IF EXISTS fly_post(text, text);

CREATE OR REPLACE FUNCTION fly_post(
    p_app_name text,
    p_action   text
)
RETURNS TABLE (status integer, content text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, extensions
AS $$
DECLARE
    v_token      text;
    v_machine_id text;
    v_url        text;
    resp         http_response;
BEGIN
    IF p_action NOT IN ('start', 'stop', 'suspend') THEN
        RAISE EXCEPTION 'Invalid action "%". Must be start | stop | suspend', p_action;
    END IF;

    SELECT api_token, machine_id
      INTO v_token, v_machine_id
      FROM fly_config
     WHERE app_name = p_app_name;

    IF v_token IS NULL OR v_machine_id IS NULL THEN
        RAISE EXCEPTION 'fly_config has no usable row for app "%"', p_app_name;
    END IF;

    v_url := 'https://api.machines.dev/v1/apps/' || p_app_name
             || '/machines/' || v_machine_id || '/' || p_action;

    -- Empty body, but pgsql-http requires a non-NULL `content` for POST, so pass ''
    -- (mirrors this repo's ordelo_post: http_post(url, '', 'application/json')).
    -- If Fly ever 400s on the empty JSON body, switch content from '' to '{}'.
    SELECT * INTO resp
      FROM http((
        'POST',
        v_url,
        ARRAY[http_header('Authorization', 'Bearer ' || v_token)],
        'application/json',   -- content_type
        ''                    -- content: empty body (must be non-NULL for POST)
      )::http_request);

    RETURN QUERY SELECT resp.status, resp.content::text;
END;
$$;

-- NOT APPLIED LIVE (2026-10-16): this REVOKE is the intended access rule, but the live function is still
-- executable by PUBLIC/anon/authenticated. Tracked in docs/to-do.md. Kept commented so this file matches live.
-- CRITICAL: a SECURITY DEFINER function in public is auto-exposed as a PostgREST RPC
-- and EXECUTE defaults to PUBLIC (anon/authenticated). Without this, anyone with the
-- anon key could stop prod, and the table RLS would NOT help (function reads as owner).
-- REVOKE EXECUTE ON FUNCTION fly_post(text, text) FROM public, anon, authenticated;

GRANT  EXECUTE ON FUNCTION fly_post(text, text) TO service_role;

-- -- Usage:
-- -- SELECT * FROM fly_post('sfcs-agent', 'stop');    -- nightly shutdown
-- -- SELECT * FROM fly_post('sfcs-agent', 'start');   -- morning boot
-- SELECT * FROM fly_post('sfcs-agent', 'stop');
-- SELECT * FROM fly_post('bnat-agent', 'stop');
