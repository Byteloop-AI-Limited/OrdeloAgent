-- ============================================================
-- Helper: POST to a URL built from ordelo_config
-- Usage: SELECT ordelo_post('SFCS_APP_URL', '/some/path', 'key=val&key2=val2');
-- ============================================================
CREATE OR REPLACE FUNCTION ordelo_post(
    p_config_key text,
    p_path       text,
    p_query      text DEFAULT ''
)
RETURNS TABLE (status integer, content text)
LANGUAGE plpgsql
AS $$
DECLARE
    base_url text;
    full_url text;
    resp     http_response;
BEGIN
    SELECT config_value INTO base_url
    FROM ordelo_config
    WHERE config_key = p_config_key;

    IF base_url IS NULL OR base_url = '' THEN
        RAISE EXCEPTION 'ordelo_config key "%" not found or empty', p_config_key;
    END IF;

    full_url := base_url || p_path;
    IF p_query <> '' THEN
        full_url := full_url || '?' || p_query;
    END IF;

    SELECT * INTO resp FROM http_post(full_url, '', 'application/json');

    RETURN QUERY SELECT resp.status, resp.content::text;
END;
$$;