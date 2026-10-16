-- Create location_event table
CREATE TABLE IF NOT EXISTS public.rider_location_event (
    id serial NOT NULL,
    topic character varying(255),
    rider_id character varying(12) NOT NULL,
    customer_id character varying(12),
    order_number character varying(100),
    rid character varying(20) NOT NULL,
    event character varying(20) NOT NULL,
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT rider_location_event_pkey PRIMARY KEY (id)
);

-- cleanup
-- drop trigger if exists trigger_rider_location_event_update on rider_location_event;
-- drop function if exists rider_location_event_update();

-- # Create a trigger on an update to table rider_location_event
CREATE OR REPLACE FUNCTION public.rider_location_event_update ()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
DECLARE
    webhook_payload json;
    app_url varchar;
    hook_url varchar;
BEGIN
    -- Build the webhook payload as just the inserted record
    webhook_payload := row_to_json(NEW);
    -- Fetch app_url from config
    SELECT
        config_value INTO app_url
    FROM
        ordelo_config
    WHERE
        config_key = 'ORDELO_APP_URL';

    IF app_url IS NULL OR length(app_url) = 0 THEN
        app_url := 'https://rider-agent.ordelo.app';
    END IF;
    -- Ensure no trailing slash before appending path
    IF
    RIGHT (app_url,
    1) = '/' THEN
        app_url :=
    LEFT (app_url,
        length(app_url) - 1);
    END IF;
    hook_url := app_url || '/location-hooks/notify-rider-location-event';
    -- Make the HTTP POST request and ignore the response
    PERFORM
        http_post (hook_url, webhook_payload::text, 'application/json');
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trigger_rider_location_event_update ON public.rider_location_event;

CREATE TRIGGER trigger_rider_location_event_update
    AFTER INSERT ON rider_location_event
    FOR EACH ROW
    EXECUTE FUNCTION rider_location_event_update ();
