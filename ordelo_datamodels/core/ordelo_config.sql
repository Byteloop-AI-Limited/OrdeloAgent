-- Table to store application configuration as key-value pairs
CREATE TABLE IF NOT EXISTS public.ordelo_config (
    config_key character varying(100) NOT NULL,
    config_value text NOT NULL,
    description text,
    created_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ordelo_config_pkey PRIMARY KEY (config_key)
);

DROP POLICY IF EXISTS "Enable read access for all users" ON public.ordelo_config;

CREATE POLICY "Enable read access for all users" ON public.ordelo_config AS PERMISSIVE
    FOR SELECT TO public
        USING (TRUE);

-- ===========================================================================
-- 3. parse_alert_offsets(config_key) -> int[]
--    '-15, -5, x, 5' -> {-15,-5,5}.  Absent/blank/all-junk -> NULL.
-- ===========================================================================
-- Junk entries are skipped rather than fatal: one stray character must not
-- silence alerts for every rider. The caller tells "absent" from "present but
-- unparseable" and RAISEs a NOTICE for the latter.
CREATE OR REPLACE FUNCTION parse_alert_offsets (p_config_key text)
    RETURNS int[]
    LANGUAGE sql
    STABLE
    AS $$
    SELECT
        array_agg(DISTINCT btrim(t.x)::int ORDER BY btrim(t.x)::int)
    FROM
        ordelo_config c
    CROSS JOIN unnest(string_to_array(c.config_value, ',')) AS t (x)
WHERE
    c.config_key = p_config_key
    AND btrim(t.x) ~ '^-?\d+$';
$$;

-- -- Optional: trigger to auto-update "updated_at" on row modification
-- CREATE OR REPLACE FUNCTION trigger_update_timestamp()
-- RETURNS TRIGGER AS $$
-- BEGIN
--     NEW.updated_at = CURRENT_TIMESTAMP;
--     RETURN NEW;
-- END;
-- $$ LANGUAGE plpgsql;

-- CREATE TRIGGER trg_app_config_updated
-- BEFORE UPDATE ON app_config
-- FOR EACH ROW
-- EXECUTE FUNCTION trigger_update_timestamp();

-- update restaurant_master 
-- set admins = '{}'::text[]
-- where rest_ref='WREN';
