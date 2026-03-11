-- Database job function to trigger stale active thread termination
-- Calls the Ordelo app endpoint which then notifies the restaurant webhook

DROP FUNCTION IF EXISTS job_terminate_stale_active_threads();

CREATE OR REPLACE FUNCTION job_terminate_stale_active_threads()
RETURNS BOOLEAN AS $$
DECLARE
    response JSON;
    notified BOOLEAN := FALSE;
    ordelo_app_url TEXT;
    webhook_url TEXT;
BEGIN
    -- Get webhook URL from config
    SELECT config_value INTO ordelo_app_url 
    FROM ordelo_config 
    WHERE config_key = 'ORDELO_APP_URL';
    
    IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
      ordelo_app_url := 'https://rider-agent.ordelo.app';
    END IF;
    
    webhook_url := ordelo_app_url || '/thread-hooks/terminate-stale-active-threads';

    response := (
        SELECT content
        FROM http_post(
             webhook_url,
             '{}'::text,
             'application/json'
        )
    );
    RAISE NOTICE 'Response from terminate-stale-active-threads: %', response;
    notified := TRUE;

    RETURN notified;
END;
$$ LANGUAGE plpgsql;


select * from job_terminate_stale_active_threads()