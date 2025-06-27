/*
Live Tracking Not Enabled Job – Notifies when rider live tracking is not enabled for inflight deliveries.
    . Reads config from ordelo_config (location_enable_time_interval, ordelo_app_url)
    . Identifies inflight deliveries with missing or stale location data
    . Aggregates (order_number, rider_id) as JSON array
    . Makes HTTP POST to /location-hooks/null-or-outdated-location
    . Returns boolean for success/failure
Functions:
    . job_null_or_outdated_location
*/
DROP FUNCTION IF EXISTS job_null_or_outdated_location();
CREATE OR REPLACE FUNCTION job_null_or_outdated_location()
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
$$ LANGUAGE plpgsql;

-- Usage:
-- select job_null_or_outdated_location();
