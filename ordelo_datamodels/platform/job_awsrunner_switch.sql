/*
AWS App Runner Switch Job – Controls AWS App Runner services by resuming or pausing them via Supabase Edge Function.
  Scheduled Execution:
    . Can be called manually or via Supabase cron job
    . Accepts 'resume' or 'pause' as action parameter
  Configuration:
    . Base URL: https://pqsvhidiwiydgshynfib.supabase.co/functions/v1/app-runner-manager
    . Services: elaib, ordelo
  Logic Flow:
    . Validates action parameter (must be 'resume' or 'pause')
    . Constructs URLs for both elaib and ordelo services
    . Makes GET requests to both endpoints sequentially
    . Logs responses from each service
    . Returns boolean indicating if both requests were successful
  Endpoints:
    . Resume: GET /app-runner-manager/{service}/resume
    . Pause: GET /app-runner-manager/{service}/pause
  Usage Examples:
    . SELECT job_awsrunner_switch('resume');  -- Start both services
    . SELECT job_awsrunner_switch('pause');   -- Stop both services
Functions:
    . job_awsrunner_switch
*/
DROP FUNCTION IF EXISTS job_awsrunner_switch(TEXT);

CREATE OR REPLACE FUNCTION job_awsrunner_switch(action TEXT)
RETURNS BOOLEAN AS $$
DECLARE
    base_url TEXT := 'https://pqsvhidiwiydgshynfib.supabase.co/functions/v1/app-runner-manager';
    elaib_url TEXT;
    ordelo_url TEXT;
    elaib_response JSON;
    ordelo_response JSON;
    success BOOLEAN := TRUE;
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
            SELECT content
            FROM http_get(elaib_url)
        );
        RAISE NOTICE 'Response from elaib (%) endpoint: %', action, elaib_response;
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'Failed to call elaib % endpoint: %', action, SQLERRM;
        success := FALSE;
    END;

    -- Make GET request to ordelo service
    BEGIN
        ordelo_response := (
            SELECT content
            FROM http_get(ordelo_url)
        );
        RAISE NOTICE 'Response from ordelo (%) endpoint: %', action, ordelo_response;
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'Failed to call ordelo % endpoint: %', action, SQLERRM;
        success := FALSE;
    END;

    RETURN success;
END;
$$ LANGUAGE plpgsql;

-- pg_cron job 'job_aws_runner_switch_pause' (live schedule: 0 23 * * *, INACTIVE). cron.schedule() updates the job in place when the name already exists.
SELECT cron.schedule('job_aws_runner_switch_pause', '0 23 * * *', $cron$SELECT job_awsrunner_switch('pause');$cron$);
SELECT cron.alter_job(jobid, active := false) FROM cron.job WHERE jobname = 'job_aws_runner_switch_pause';

-- pg_cron job 'job_awsrunner_switch_resume' (live schedule: 0 6 * * *, INACTIVE). cron.schedule() updates the job in place when the name already exists.
SELECT cron.schedule('job_awsrunner_switch_resume', '0 6 * * *', $cron$SELECT job_awsrunner_switch('resume');$cron$);
SELECT cron.alter_job(jobid, active := false) FROM cron.job WHERE jobname = 'job_awsrunner_switch_resume';

-- Usage:
-- SELECT job_awsrunner_switch('resume');  -- Start both App Runner services
-- SELECT job_awsrunner_switch('pause');   -- Stop both App Runner services
