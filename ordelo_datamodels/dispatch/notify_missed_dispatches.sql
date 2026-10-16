DROP FUNCTION IF EXISTS notify_missed_dispatches();

CREATE OR REPLACE FUNCTION notify_missed_dispatches() RETURNS BOOLEAN AS $$
DECLARE
    response json;
    webhook_payload json;
    notified BOOLEAN := FALSE;
    app_url VARCHAR;
    hook_url VARCHAR;
BEGIN
    WITH missed_dispatches AS (
        SELECT
            dd.order_number,
            json_agg(json_build_object(
                'dispatch_id', d.dispatch_id,
                'rider_id', d.rider_id,
                'order_number', d.order_number,
                'order_status', dd.status,
                'dtts', d.dtts
            )) AS dispatches
        FROM delivery_dispatch d
        INNER JOIN delivery_detail dd ON d.order_number = dd.order_number
        WHERE d.status = 'accepted'
        -- AND DATE(d.dtts) = DATE(dd.dtts)
        AND dd.status = 'assigned'
        GROUP BY dd.order_number
    )
    SELECT
        json_build_object(
            'missed_dispatches', (
                SELECT json_agg(row_to_json(md))
                FROM missed_dispatches md
            )
        ) INTO webhook_payload;

    -- Make the HTTP POST request with the payload
    SELECT config_value INTO app_url
    FROM ordelo_config
   WHERE config_key = 'ORDELO_APP_URL';

  IF app_url IS NULL OR length(app_url) = 0 THEN
    app_url := 'https://agent.ordelo.app';
  END IF;

  -- Ensure no trailing slash before appending path
  IF right(app_url, 1) = '/' THEN
    app_url := left(app_url, length(app_url) - 1);
  END IF;
  hook_url := app_url || '/delivery-hooks/notify-missed-dispatches';
    response := (
        SELECT content
        FROM http_post(
            hook_url,
            webhook_payload::text,
            'application/json'
        )
    );

    -- Log the response
    RAISE NOTICE 'Response from notify-missed-dispatches: %', response;
    notified := TRUE;

    RETURN notified;
END;
$$ LANGUAGE plpgsql;
