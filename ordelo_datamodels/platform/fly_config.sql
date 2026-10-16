-- Per-app Fly.io control config (token + target machine), keyed by app_name.
-- Holds a secret (api_token) that can stop/start production Machines, so it is
-- locked out of the PostgREST/anon API; only fly_post() (SECURITY DEFINER) reads it.
-- Lock down: RLS enabled + no policies => deny-all; then revoke table grants from API roles.
-- This keeps the api_token unreachable through the public PostgREST/anon interface.
CREATE TABLE IF NOT EXISTS public.fly_config (
    app_name character varying(100) NOT NULL, -- = FLY_APP_NAME, e.g. 'sfcs-agent'
    api_token text NOT NULL, -- = FLY_API_TOKEN (app-scoped deploy token)
    machine_id text NOT NULL, -- = FLY_MACHINE_ID
    region text, -- optional, informational (e.g. 'lhr')
    description text,
    created_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fly_config_pkey PRIMARY KEY (app_name)
);

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- One-time row insert (fill in real values; token from the `fly tokens create deploy` step
-- in docs/fly.io-deploy-guide.md, machine id from `fly machine list -a sfcs-agent`):
-- INSERT INTO fly_config (app_name, machine_id, region, api_token, description)
-- VALUES ('sfcs-agent', '<FLY_MACHINE_ID>', 'lhr', '<FLY_API_TOKEN>', 'nightly stop/start');
-- Token below has ot be generated for each app
-- INSERT INTO fly_config (app_name, machine_id, region, api_token, description)
-- VALUES (
--     'sfcs-**',
--     '84edec***',
--     'lhr',
--     '',
--     'nightly stop/start'
-- )
-- ON CONFLICT (app_name) DO UPDATE
--    SET machine_id  = EXCLUDED.machine_id,
--        region      = EXCLUDED.region,
--        api_token   = EXCLUDED.api_token,
--        description = EXCLUDED.description,
--        updated_at  = CURRENT_TIMESTAMP;

-- select * from fly_config;
