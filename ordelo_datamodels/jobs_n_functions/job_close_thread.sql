/*
Close Thread Job – Closes inactive threads that haven't been accessed recently and are not marked for retention.
  Scheduled Execution:
    . Runs every 5 minutes via Supabase cron job
    . Cron expression: '*5 * * * *'
  Configuration:
    . THREAD_INACTIVE_TIME_INTERVAL - Minutes of inactivity before thread closure (default: 5)
    . ORDELO_APP_URL - Base URL for webhook calls (default: https://rider-agent.ordelo.app)
  Logic Flow:
    . Queries thread table for inactive threads
    . Filters: last_access_dtts older than interval AND retain_thread = false
    . Aggregates matching records as JSON array with thread_id, recipient, last_access_dtts, is_active, minutes_since_last_access
    . Makes HTTP POST to /delivery-hooks/close-threads webhook endpoint
    . Returns boolean indicating if threads were found and notified
  Webhook Integration:
    . Endpoint: POST /delivery-hooks/close-threads
    . Payload: JSON array of thread records
    . Triggers thread closure and goodbye message to recipients
Functions:
    . job_close_thread
*/
DROP FUNCTION IF EXISTS job_close_thread();
CREATE OR REPLACE FUNCTION job_close_thread()
RETURNS BOOLEAN AS $$
DECLARE
    interval_minutes INT;
    interval_expr INTERVAL;
    webhook_payload JSON;
    response JSON;
    notified BOOLEAN := FALSE;
    ordelo_app_url TEXT;
    webhook_url TEXT;
BEGIN
    -- Get the interval in minutes from config
    SELECT config_value::int INTO interval_minutes FROM ordelo_config WHERE config_key = 'THREAD_INACTIVE_TIME_INTERVAL';
    IF interval_minutes IS NULL THEN
        interval_minutes := 5; -- Default fallback (5 minutes)
    END IF;
    interval_expr := (interval_minutes || ' minutes')::interval;

    -- Get the base app URL from config
    SELECT config_value INTO ordelo_app_url FROM ordelo_config WHERE config_key = 'ORDELO_APP_URL';
    IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
        ordelo_app_url := 'https://rider-agent.ordelo.app'; -- Fallback default
    END IF;
    webhook_url := ordelo_app_url || '/delivery-hooks/close-threads';

    WITH threads_to_close AS (
        SELECT
            thread_id,
            recipient,
            last_access_dtts,
            is_active,
            EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - last_access_dtts))/60 AS minutes_since_last_access
        FROM thread
        WHERE last_access_dtts IS NOT NULL
          AND CURRENT_TIMESTAMP - last_access_dtts > interval_expr
          AND retain_thread = FALSE
          AND is_active = TRUE
    )
    SELECT json_agg(
        json_build_object(
            'thread_id', thread_id, 
            'recipient', recipient, 
            'last_access_dtts', last_access_dtts,
            'is_active', is_active,
            'minutes_since_last_access', minutes_since_last_access
        )
    )
    INTO webhook_payload
    FROM threads_to_close;

    -- Only POST if there is at least one thread to close
    IF webhook_payload IS NOT NULL THEN
        response := (
            SELECT content
            FROM http_post(
                webhook_url,
                webhook_payload::text,
                'application/json'
            )
        );
        RAISE NOTICE 'Response from close-threads: %', response;
        notified := TRUE;
    ELSE
        RAISE NOTICE 'No threads to close.';
        notified := FALSE;
    END IF;
    RETURN notified;
END;
$$ LANGUAGE plpgsql;

-- Usage:
-- select job_close_thread();
