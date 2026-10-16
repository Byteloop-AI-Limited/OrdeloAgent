-- =============================================================================================
-- ordelo_datamodels/platform/job_awsrunner_switch.sql
-- Pause or resume the AWS App Runner services (elaib, ordelo) through a Supabase Edge Function (cron jobs INACTIVE).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     job_awsrunner_switch(action text) -> boolean
--                   Pause or resume both App Runner services; returns true when both calls succeeded.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call makes two HTTP GETs to the edge function.
-- HOW IT FITS   job_awsrunner_switch('pause' | 'resume') calls the Supabase Edge Function app-runner-manager for each service
--                 (GET /functions/v1/app-runner-manager/{service}/{action}). Two cron jobs (pause 23:00, resume 06:00 UTC) exist but are
--                 inactive on live.
-- LIFECYCLE     none
-- CALLED BY     job_awsrunner_switch:
--                 cron      'job_aws_runner_switch_pause' 0 23 * * * (INACTIVE)
--                 cron      'job_awsrunner_switch_resume' 0 6 * * * (INACTIVE)
-- PYTHON MODEL  none
-- SECURITY      job_awsrunner_switch(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       The edge-function base URL is hard-coded in the function body.
-- SEE ALSO      docs/fly.io-deploy-guide.md (current hosting)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function job_awsrunner_switch(action text) -> boolean
--   Pause or resume both App Runner services; returns true when both calls succeeded.
--   HTTP: POST /elaib/; POST /ordelo/
-- ---------------------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS job_awsrunner_switch (TEXT);

CREATE OR REPLACE FUNCTION job_awsrunner_switch (action text)
    RETURNS boolean
    AS $$
DECLARE
    base_url text := 'https://pqsvhidiwiydgshynfib.supabase.co/functions/v1/app-runner-manager';
    elaib_url text;
    ordelo_url text;
    elaib_response json;
    ordelo_response json;
    success boolean := TRUE;
BEGIN
    -- Validate action parameter
    IF action NOT IN ('resume', 'pause') THEN
        RAISE EXCEPTION 'Invalid action: %. Must be either ''resume'' or ''pause''', action;
    END IF;
    -- Construct URLs
    elaib_url := base_url || '/elaib/' || action;
    ordelo_url := base_url || '/ordelo/' || action;
    -- Make GET request to elaib service
    BEGIN
        elaib_response := (
            SELECT
                content
            FROM
                http_get (elaib_url));
        RAISE NOTICE 'Response from elaib (%) endpoint: %', action, elaib_response;
    EXCEPTION
        WHEN OTHERS THEN
            RAISE WARNING 'Failed to call elaib % endpoint: %', action, SQLERRM;
            success := FALSE;
    END;
    -- Make GET request to ordelo service
    BEGIN
        ordelo_response := (
            SELECT
                content
            FROM
                http_get (ordelo_url));
        RAISE NOTICE 'Response from ordelo (%) endpoint: %', action, ordelo_response;
    EXCEPTION
        WHEN OTHERS THEN
            RAISE WARNING 'Failed to call ordelo % endpoint: %', action, SQLERRM;
            success := FALSE;
    END;

    RETURN success;
END;

$$
LANGUAGE plpgsql;

-- pg_cron job 'job_aws_runner_switch_pause': runs every 0 23 * * *, INACTIVE (re-disabled by the next statement) on live.
-- cron.schedule() with an existing job name updates that job in place, so re-running is safe.
SELECT
    cron.schedule ('job_aws_runner_switch_pause', '0 23 * * *', 'SELECT job_awsrunner_switch(''pause'');');

SELECT
    cron.alter_job (jobid, active := FALSE)
FROM
    cron.job
WHERE
    jobname = 'job_aws_runner_switch_pause';

-- pg_cron job 'job_awsrunner_switch_resume': runs every 0 6 * * *, INACTIVE (re-disabled by the next statement) on live.
-- cron.schedule() with an existing job name updates that job in place, so re-running is safe.
SELECT
    cron.schedule ('job_awsrunner_switch_resume', '0 6 * * *', 'SELECT job_awsrunner_switch(''resume'');');

SELECT
    cron.alter_job (jobid, active := FALSE)
FROM
    cron.job
WHERE
    jobname = 'job_awsrunner_switch_resume';

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.job_awsrunner_switch (action text) IS 'Pause or resume both App Runner services; returns true when both calls succeeded.';

-- Usage:
-- SELECT job_awsrunner_switch('resume');  -- Start both App Runner services
-- SELECT job_awsrunner_switch('pause');   -- Stop both App Runner services
