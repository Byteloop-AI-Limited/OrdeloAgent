-- Updated DDL statement for the delivery_inflight_location_events table with all fields
CREATE TABLE IF NOT EXISTS rider_location (
    topic VARCHAR(255),
    rider_id VARCHAR(12),
    customer_id VARCHAR(12),
    order_number VARCHAR(100),
    acc INTEGER,
    alt INTEGER,
    batt INTEGER,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    tst INTEGER,
    tid VARCHAR(255),
    conn VARCHAR(1),
    inregions TEXT[],
    inrids TEXT[],
    created_at INTEGER,
    m INTEGER,
    tst_dtts TIMESTAMP,
    dt DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- drop table


CREATE INDEX IF NOT EXISTS idx_rider_location_tst_desc ON rider_location (tst DESC);
CREATE INDEX IF NOT EXISTS idx_rider_location_dtts_desc ON rider_location (dtts DESC);

-- Create location_event table
CREATE TABLE IF NOT EXISTS rider_location_event (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255),
    rider_id VARCHAR(12) NOT NULL,
    customer_id VARCHAR(12),
    order_number VARCHAR(100),
    rid VARCHAR(20) NOT NULL,
    event VARCHAR(20) NOT NULL,
    dt DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER trigger_rider_location_event_update
    AFTER INSERT ON rider_location_event
    FOR EACH ROW
    EXECUTE PROCEDURE rider_location_event_update();

-- cleanup
-- drop trigger if exists trigger_rider_location_event_update on rider_location_event;
-- drop function if exists rider_location_event_update();

-- # Create a trigger on an update to table rider_location_event
CREATE OR REPLACE FUNCTION public.rider_location_event_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  webhook_payload json;
  app_url VARCHAR;
  hook_url VARCHAR;
BEGIN
  -- Build the webhook payload as just the inserted record
  webhook_payload := row_to_json(NEW);

  -- Fetch app_url from config
  SELECT config_value INTO app_url
    FROM ordelo_config
   WHERE config_key = 'ORDELO_APP_URL';

  IF app_url IS NULL OR length(app_url) = 0 THEN
    app_url := 'https://rider-agent.ordelo.app';
  END IF;

  -- Ensure no trailing slash before appending path
  IF right(app_url, 1) = '/' THEN
    app_url := left(app_url, length(app_url) - 1);
  END IF;
  hook_url := app_url || '/location-hooks/notify-rider-location-event';

  -- Make the HTTP POST request and ignore the response
  PERFORM http_post(
    hook_url,
    webhook_payload::text,
    'application/json'
  );
  RETURN NEW;
END;
$$;

