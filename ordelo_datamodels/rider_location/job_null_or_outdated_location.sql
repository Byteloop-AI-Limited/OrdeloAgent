-- Definition taken from the live database on 2026-10-16 (the previous repo copy in rider_location/job_null_or_outdated_location.sql differed).
CREATE OR REPLACE FUNCTION public.job_null_or_outdated_location()
 RETURNS boolean
 LANGUAGE plpgsql
AS $function$
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
    SELECT config_value::int INTO interval_minutes FROM ordelo_config WHERE config_key = 'LOCATION_ENABLE_TIME_INTERVAL';
    IF interval_minutes IS NULL THEN
        interval_minutes := 1; -- Default fallback
    END IF;
    interval_expr := (interval_minutes || ' minutes')::interval;

    -- Get the base app URL from config
    SELECT config_value INTO ordelo_app_url FROM ordelo_config WHERE config_key = 'ORDELO_APP_URL';
    IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
        ordelo_app_url := 'https://rider-agent.ordelo.app'; -- Fallback default
    END IF;
    webhook_url := ordelo_app_url || '/location-hooks/null-or-outdated-location';

    WITH inflight_missing_location AS (
        SELECT
            inflight.order_number,
            inflight.rider_id,
            MAX(location.dtts) as last_location_dtts
        FROM delivery_inflight inflight
        LEFT JOIN rider_location location
            ON inflight.order_number = location.order_number
            AND inflight.rider_id = location.rider_id
        GROUP BY inflight.order_number, inflight.rider_id
    ), inflight_to_notify AS (
        SELECT
            order_number,
            rider_id,
            last_location_dtts AS dtts,
            CASE WHEN last_location_dtts IS NULL THEN 'NO_LOCATION_DATA'
            ELSE 'OUTDATED_LOCATION_DATA'
            END as reason
        FROM inflight_missing_location
        WHERE last_location_dtts IS NULL
           OR (current_timestamp - last_location_dtts) > interval_expr
    )
    SELECT json_agg(json_build_object('order_number', order_number, 'rider_id', rider_id, 'reason', reason, 'dtts', dtts))
      INTO webhook_payload
      FROM inflight_to_notify;

    -- Only POST if there is at least one item
    IF webhook_payload IS NOT NULL THEN
        response := (
            SELECT content
            FROM http_post(
                webhook_url,
                webhook_payload::text,
                'application/json'
            )
        );
        RAISE NOTICE 'Response from null-or-outdated-location: %', response;
        notified := TRUE;
    ELSE
        RAISE NOTICE 'No inflight deliveries missing location data.';
        notified := FALSE;
    END IF;
    RETURN notified;
END;
$function$;

-- pg_cron job 'job_null_or_outdated_location' (live schedule: * * * * *, INACTIVE). cron.schedule() updates the job in place when the name already exists.
SELECT cron.schedule('job_null_or_outdated_location', '* * * * *', $cron$SELECT public.job_null_or_outdated_location()$cron$);
SELECT cron.alter_job(jobid, active := false) FROM cron.job WHERE jobname = 'job_null_or_outdated_location';

-- Usage:
-- select job_null_or_outdated_location();
