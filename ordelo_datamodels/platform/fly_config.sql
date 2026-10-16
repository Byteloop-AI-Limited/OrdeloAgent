-- =============================================================================================
-- ordelo_datamodels/platform/fly_config.sql
-- Fly.io control config per app (API token + target machine), read only by fly_post().
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16), which does NOT have the intended lock-down: see GOTCHAS.
-- OBJECTS       table  fly_config
--                   One row per Fly app: app-scoped API token, machine id, region and description.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   fly_post(app, action) reads the app's api_token and machine_id here and calls the Fly Machines API (start / stop /
--                 suspend), e.g. for a nightly stop of a restaurant agent. See docs/fly.io-deploy-guide.md.
-- LIFECYCLE     none
-- CALLED BY     fly_config:
--                 sql       fly_post()
-- PYTHON MODEL  none
-- SECURITY      fly_config: RLS OFF; default grants: anon and authenticated can read the API tokens (2 rows with tokens on 2026-10-16).
--               Intended: RLS on with no policies + REVOKE ALL FROM anon, authenticated (kept commented at the end of this file).
-- TESTS         none
-- GOTCHAS       URGENT (docs/to-do.md): apply the lock-down and rotate the tokens.
--               updated_at is not maintained automatically; set it by hand on UPDATE.
-- SEE ALSO      platform/fly_post.sql
--               docs/fly.io-deploy-guide.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table fly_config
--   One row per Fly app: app-scoped API token, machine id, region and description.
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- NOT APPLIED LIVE (2026-10-16): the intended lock-down. Run these, then rotate the tokens (docs/to-do.md).
-- They are commented so this file still describes the live database exactly; uncomment them in the same change
-- that applies them to live.
-- ---------------------------------------------------------------------------------------------
-- ALTER TABLE public.fly_config ENABLE ROW LEVEL SECURITY;
-- REVOKE ALL ON TABLE public.fly_config FROM anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.fly_config IS 'One row per Fly app: app-scoped API token, machine id, region and description.';

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
