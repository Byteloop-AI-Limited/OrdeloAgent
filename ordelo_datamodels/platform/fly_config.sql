-- =============================================================================================
-- ordelo_datamodels/platform/fly_config.sql
-- Fly.io control config per app (API token + target machine), and the idle-suspend job that uses it.
-- =============================================================================================
-- LIVE CHECK    table DDL matched live on 2026-10-16. NOT YET APPLIED TO LIVE (2026-11-16): the RLS lock-down, the two
--                 last_idle_check columns and fly_idle_suspend(). Apply this whole file, then tick the item in docs/to-do.md.
-- OBJECTS       table  fly_config
--                   One row per Fly app: app-scoped API token, machine id, region, description and the last idle check.
--               alter  fly_config ADD COLUMN last_idle_check, last_idle_check_at
--                   Outcome of the most recent fly_idle_suspend() run for the app.
--               fn     fly_idle_suspend(p_min_idle_seconds integer, p_dry_run boolean) -> jsonb
--                   Suspend each started Fly machine whose agent reports no work and idle_seconds >= p_min_idle_seconds.
-- REQUIRES      platform/fly_post.sql (fly_idle_suspend calls fly_post to send the suspend)
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  fly_idle_suspend makes, per app: one GET to the Fly Machines API, one GET to the agent's /internal/activity
--                 (only when the machine is started) and, when idle, one POST suspend via fly_post (can suspend production).
--                 It writes last_idle_check / last_idle_check_at on fly_config and a RAISE LOG line per app.
-- HOW IT FITS   fly_post(app, action) reads the app's api_token and machine_id here and calls the Fly Machines API (start / stop /
--                 suspend). fly_idle_suspend() is the idle-aware caller meant for pg_cron (every 10 min):
--                   1. GET https://api.machines.dev/v1/apps/<app>/machines/<id>; skip unless state = 'started'
--                      (calling the agent while suspended would wake it: auto_start_machines = true).
--                   2. GET https://<app>.fly.dev/internal/activity (restaurant-agents runtime, app_factory.py).
--                   3. If active_requests, active_jobs, active_agent_runs are 0, draining is false and
--                      idle_seconds >= p_min_idle_seconds (default 3600), call fly_post(app, 'suspend').
--                 The next WhatsApp webhook wakes the machine again (Fly auto-start). See docs/fly.io-deploy-guide.md.
-- LIFECYCLE     none
-- CALLED BY     fly_config:
--                 sql       fly_post(), fly_idle_suspend()
--               fly_idle_suspend:
--                 cron      'job_fly_idle_suspend' */10 * * * * (NOT SCHEDULED: see the commented example at the end of this file)
-- PYTHON MODEL  none
-- SECURITY      fly_config: RLS on with no policies; ALL revoked from anon, authenticated (tokens readable by the owner only).
--               fly_idle_suspend(): SECURITY DEFINER; EXECUTE revoked from PUBLIC, anon, authenticated; granted to service_role.
--               Until this file is applied, live still lets anon read the tokens (docs/to-do.md): rotate them after applying.
-- TESTS         none
-- GOTCHAS       updated_at is not maintained automatically; set it by hand on UPDATE (fly_idle_suspend does not touch it).
--               machine_id is not refreshed automatically: a redeploy that replaces the machine needs the row updated
--                 (fly machine list -a <app>), otherwise the state check returns 404 and the app is never suspended.
--               The agent URL is derived as https://<app_name>.fly.dev.
--               idle_seconds restarts from 0 when the agent process starts or resumes, so a woken machine waits a full
--                 p_min_idle_seconds before it can be suspended again.
-- SEE ALSO      platform/fly_post.sql
--               docs/fly.io-deploy-guide.md
--               restaurant-agents: docs/webhook_endpoints.md (Activity Endpoint), watomation/activity.py
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table fly_config
--   One row per Fly app: app-scoped API token, machine id, region, description and the last idle check.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.fly_config (
    app_name character varying(100) NOT NULL, -- = FLY_APP_NAME, e.g. 'sfcs-agent'
    api_token text NOT NULL, -- = FLY_API_TOKEN (app-scoped deploy token)
    machine_id text NOT NULL, -- = FLY_MACHINE_ID
    region text, -- optional, informational (e.g. 'lhr')
    description text,
    created_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_idle_check jsonb, -- outcome object written by fly_idle_suspend() (result, state, activity, ...)
    last_idle_check_at timestamp with time zone, -- when fly_idle_suspend() last checked this app
    CONSTRAINT fly_config_pkey PRIMARY KEY (app_name)
);

-- Columns added on 2026-11-16 for fly_idle_suspend(); no-ops on a table created by the statement above.
ALTER TABLE public.fly_config
    ADD COLUMN IF NOT EXISTS last_idle_check jsonb;

ALTER TABLE public.fly_config
    ADD COLUMN IF NOT EXISTS last_idle_check_at timestamp with time zone;

-- ---------------------------------------------------------------------------------------------
-- Lock-down: the table holds Fly API tokens that can stop, start and suspend production.
-- RLS on with no policies denies every PostgREST role; the REVOKE removes the default grants as well.
-- SECURITY DEFINER functions (fly_post, fly_idle_suspend) still read it as the owner.
-- After applying, rotate both tokens (they were readable with the anon key) and update the rows.
-- ---------------------------------------------------------------------------------------------
ALTER TABLE public.fly_config ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.fly_config FROM anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function fly_idle_suspend(p_min_idle_seconds integer DEFAULT 3600, p_dry_run boolean DEFAULT false) -> jsonb
--   Suspend each started Fly machine whose agent reports no work and idle_seconds >= p_min_idle_seconds.
--   Arguments: p_min_idle_seconds  idle time required before suspending (default one hour)
--              p_dry_run           true = run every check but never suspend (result 'would_suspend')
--   Returns:   {"result": "ok", "dry_run": bool, "min_idle_seconds": int, "apps": [<outcome>, ...]}
--   Outcome per app (also stored in fly_config.last_idle_check), "result" is one of:
--              skipped_not_started   machine state is not 'started' (already suspended/stopped): agent not called
--              busy                  a counter is > 0 or the agent is draining
--              not_idle_long_enough  idle_seconds < p_min_idle_seconds
--              would_suspend         idle long enough, p_dry_run = true
--              suspended             fly_post(app, 'suspend') returned HTTP 200
--              suspend_error         fly_post returned another status
--              fly_state_error       the Machines API state GET did not return 200 (bad token or stale machine_id)
--              activity_error        /internal/activity did not return 200
--              error                 any other exception (timeout, bad JSON); "message" holds SQLERRM
--   Data: reads fly_config; writes fly_config.last_idle_check, last_idle_check_at.
--   HTTP: GET api.machines.dev /machines/<id>; GET <app>.fly.dev/internal/activity; POST suspend via fly_post.
--   One app failing never stops the others: each app runs in its own exception block.
-- ---------------------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS fly_idle_suspend (integer, boolean);

CREATE OR REPLACE FUNCTION fly_idle_suspend (p_min_idle_seconds integer DEFAULT 3600, p_dry_run boolean DEFAULT FALSE)
    RETURNS jsonb
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = public,
    extensions
    AS $$
DECLARE
    r record;
    v_resp http_response;
    v_state text;
    v_activity jsonb;
    v_status integer;
    v_content text;
    v_outcome jsonb;
    v_apps jsonb := '[]'::jsonb;
BEGIN
    -- Keep a slow Fly or agent response from holding the cron worker.
    PERFORM
        http_set_curlopt ('CURLOPT_TIMEOUT', '10');

    FOR r IN
    SELECT
        app_name,
        api_token,
        machine_id
    FROM
        fly_config
    ORDER BY
        app_name LOOP
            v_state := NULL;
            v_activity := NULL;
            BEGIN
                -- 1. Machine state from the Fly Machines API.
                SELECT
                    * INTO v_resp
                FROM
                    http (('GET', 'https://api.machines.dev/v1/apps/' || r.app_name || '/machines/' || r.machine_id, ARRAY[http_header ('Authorization', 'Bearer ' || r.api_token)], NULL, NULL)::http_request);

                IF v_resp.status <> 200 THEN
                    v_outcome := jsonb_build_object('result', 'fly_state_error', 'http_status', v_resp.status, 'body', left(v_resp.content, 300));
                ELSE
                    v_state := v_resp.content::jsonb ->> 'state';

                    IF v_state IS DISTINCT FROM 'started' THEN
                        v_outcome := jsonb_build_object('result', 'skipped_not_started');
                    ELSE
                        -- 2. Activity from the agent itself (only now: calling a suspended machine wakes it).
                        SELECT
                            * INTO v_resp
                        FROM
                            http_get ('https://' || r.app_name || '.fly.dev/internal/activity');

                        IF v_resp.status <> 200 THEN
                            v_outcome := jsonb_build_object('result', 'activity_error', 'http_status', v_resp.status, 'body', left(v_resp.content, 300));
                        ELSE
                            v_activity := v_resp.content::jsonb;

                            IF coalesce((v_activity ->> 'active_requests')::int, 1) > 0
                                OR coalesce((v_activity ->> 'active_jobs')::int, 1) > 0
                                OR coalesce((v_activity ->> 'active_agent_runs')::int, 1) > 0
                                OR coalesce((v_activity ->> 'draining')::boolean, TRUE) THEN
                                v_outcome := jsonb_build_object('result', 'busy');
                            ELSIF coalesce((v_activity ->> 'idle_seconds')::numeric, 0) < p_min_idle_seconds THEN
                                v_outcome := jsonb_build_object('result', 'not_idle_long_enough');
                            ELSIF p_dry_run THEN
                                v_outcome := jsonb_build_object('result', 'would_suspend');
                            ELSE
                                -- 3. Suspend through the existing helper.
                                SELECT
                                    fp.status,
                                    fp.content INTO v_status,
                                    v_content
                                FROM
                                    fly_post (r.app_name, 'suspend') AS fp;

                                v_outcome := jsonb_build_object('result', CASE WHEN v_status = 200 THEN
                                            'suspended'
                                        ELSE
                                            'suspend_error'
                                        END, 'http_status', v_status, 'body', left(v_content, 300));
                            END IF;
                        END IF;
                    END IF;
                END IF;
            EXCEPTION
                WHEN OTHERS THEN
                    v_outcome := jsonb_build_object('result', 'error', 'message', SQLERRM);
            END;

            v_outcome := v_outcome || jsonb_build_object('app_name', r.app_name, 'machine_state', v_state, 'activity', v_activity, 'min_idle_seconds', p_min_idle_seconds, 'dry_run', p_dry_run);

            UPDATE
                fly_config
            SET
                last_idle_check = v_outcome,
                last_idle_check_at = CURRENT_TIMESTAMP
            WHERE
                app_name = r.app_name;

            RAISE LOG 'fly_idle_suspend %: %', r.app_name, v_outcome;

            v_apps := v_apps || jsonb_build_array(v_outcome);
        END LOOP;

    RETURN jsonb_build_object('result', 'ok', 'dry_run', p_dry_run, 'min_idle_seconds', p_min_idle_seconds, 'apps', v_apps);
END;
$$;

-- SECURITY DEFINER in public is auto-exposed as a PostgREST RPC with EXECUTE granted to PUBLIC by default:
-- without this REVOKE anyone holding the anon key could suspend production.
REVOKE ALL ON FUNCTION fly_idle_suspend (integer, boolean) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION fly_idle_suspend (integer, boolean) TO service_role;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.fly_config IS 'One row per Fly app: app-scoped API token, machine id, region, description and the last idle check.';

COMMENT ON COLUMN public.fly_config.last_idle_check IS 'Outcome of the most recent fly_idle_suspend() run for the app.';

COMMENT ON COLUMN public.fly_config.last_idle_check_at IS 'When fly_idle_suspend() last checked this app.';

COMMENT ON FUNCTION public.fly_idle_suspend (p_min_idle_seconds integer, p_dry_run boolean) IS 'Suspend each started Fly machine whose agent reports no work and idle_seconds >= p_min_idle_seconds.';

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

select * from fly_config;

-- Idle suspend: try it first without suspending anything, then for real.
-- SELECT fly_idle_suspend();              -- checks only; result 'would_suspend' when idle enough
-- SELECT fly_idle_suspend(p_dry_run := true);              -- checks only; result 'would_suspend' when idle enough
-- SELECT fly_idle_suspend(p_min_idle_seconds := 60, p_dry_run := true);   -- quick test with a 1-minute threshold
-- SELECT fly_idle_suspend();                               -- suspends apps idle >= 1 hour

-- What happened on the last run, per app:
-- SELECT app_name, last_idle_check_at, last_idle_check ->> 'result' AS result,
--        last_idle_check -> 'activity' ->> 'idle_seconds' AS idle_seconds, last_idle_check
-- FROM fly_config ORDER BY app_name;

-- Schedule every 10 minutes (cron.schedule with an existing name updates the job in place):
-- SELECT cron.schedule('job_fly_idle_suspend', '*/10 * * * *', 'SELECT fly_idle_suspend();');
-- Pause it:   SELECT cron.alter_job(jobid, active := false) FROM cron.job WHERE jobname = 'job_fly_idle_suspend';
-- Remove it:  SELECT cron.unschedule('job_fly_idle_suspend');
-- Recent runs: SELECT status, return_message, start_time FROM cron.job_run_details
--              WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'job_fly_idle_suspend')
--              ORDER BY start_time DESC LIMIT 20;