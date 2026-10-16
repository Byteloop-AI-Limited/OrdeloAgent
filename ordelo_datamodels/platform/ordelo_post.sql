-- =============================================================================================
-- ordelo_datamodels/platform/ordelo_post.sql
-- Helper: POST to a URL built from an ordelo_config key plus a path and query string.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16). No caller found (operator helper).
-- OBJECTS       fn     ordelo_post(p_config_key text, p_path text, p_query text) -> TABLE(status integer, content text)
--                   POST to <config value of p_config_key> + p_path (+ ?p_query) and return the HTTP status and body; RAISE when the key is missing.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call makes one HTTP POST.
-- HOW IT FITS   Usage: SELECT ordelo_post('SFCS_APP_URL', '/some/path', 'key=val&key2=val2');
--                 Kept as an operator helper; no function, trigger or cron job calls it on 16 Oct 2026 (triggers build their URLs inline).
-- LIFECYCLE     none
-- CALLED BY     ordelo_post:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      ordelo_post(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       none
-- SEE ALSO      platform/fly_post.sql
--               core/ordelo_config.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function ordelo_post(p_config_key text, p_path text, p_query text) -> TABLE(status integer, content text)
--   POST to <config value of p_config_key> + p_path (+ ?p_query) and return the HTTP status and body; RAISE when the key is missing.
--   Data: reads ordelo_config.
--   HTTP: POST (HTTP call, URL built at runtime)
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ordelo_post (p_config_key text, p_path text, p_query text DEFAULT '')
    RETURNS TABLE (
        status integer,
        content text)
    LANGUAGE plpgsql
    AS $$
DECLARE
    base_url text;
    full_url text;
    resp http_response;
BEGIN
    SELECT
        config_value INTO base_url
    FROM
        ordelo_config
    WHERE
        config_key = p_config_key;

    IF base_url IS NULL OR base_url = '' THEN
        RAISE EXCEPTION 'ordelo_config key "%" not found or empty', p_config_key;
    END IF;

    full_url := base_url || p_path;
    IF p_query <> '' THEN
        full_url := full_url || '?' || p_query;
    END IF;

    SELECT
        * INTO resp
    FROM
        http_post (full_url, '', 'application/json');

    RETURN QUERY
    SELECT
        resp.status,
        resp.content::text;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.ordelo_post (p_config_key text, p_path text, p_query text) IS 'POST to <config value of p_config_key> + p_path (+ ?p_query) and return the HTTP status and body; RAISE when the key is missing.';
