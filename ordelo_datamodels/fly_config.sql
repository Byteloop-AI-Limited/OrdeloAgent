-- Per-app Fly.io control config (token + target machine), keyed by app_name.
-- Holds a secret (api_token) that can stop/start production Machines, so it is
-- locked out of the PostgREST/anon API; only fly_post() (SECURITY DEFINER) reads it.
CREATE TABLE IF NOT EXISTS fly_config (
    app_name     VARCHAR(100) PRIMARY KEY,   -- = FLY_APP_NAME, e.g. 'sfcs-agent'
    api_token    TEXT NOT NULL,              -- = FLY_API_TOKEN (app-scoped deploy token)
    machine_id   TEXT NOT NULL,              -- = FLY_MACHINE_ID
    region       TEXT,                       -- optional, informational (e.g. 'lhr')
    description  TEXT,
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    -- NOTE: updated_at is NOT auto-maintained (matches ordelo_config; set it by hand on UPDATE).
);

-- Lock down: RLS enabled + no policies => deny-all; then revoke table grants from API roles.
-- This keeps the api_token unreachable through the public PostgREST/anon interface.
ALTER TABLE fly_config ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON fly_config FROM anon, authenticated;

-- One-time row insert (fill in real values; token from the `fly tokens create deploy` step
-- in docs/fly.io-deploy-guide.md, machine id from `fly machine list -a sfcs-agent`):
-- INSERT INTO fly_config (app_name, machine_id, region, api_token, description)
-- VALUES ('sfcs-agent', '<FLY_MACHINE_ID>', 'lhr', '<FLY_API_TOKEN>', 'nightly stop/start');
-- Token below has ot be generated for each app

INSERT INTO fly_config (app_name, machine_id, region, api_token, description)
VALUES (
    'sfcs-**',
    '84edec***',
    'lhr',
    '',
    'nightly stop/start'
)
ON CONFLICT (app_name) DO UPDATE
   SET machine_id  = EXCLUDED.machine_id,
       region      = EXCLUDED.region,
       api_token   = EXCLUDED.api_token,
       description = EXCLUDED.description,
       updated_at  = CURRENT_TIMESTAMP;
    


select * from fly_config;