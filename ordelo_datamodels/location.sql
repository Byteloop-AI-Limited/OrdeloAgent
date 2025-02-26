-- Updated DDL statement for the delivery_inflight_location_events table with all fields
CREATE TABLE IF NOT EXISTS rider_location (
    topic VARCHAR(255),
    rider_id VARCHAR(25),
    recipient VARCHAR(25),
    order_number VARCHAR(25),
    acc INTEGER,
    alt INTEGER,
    batt INTEGER,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    t VARCHAR(1),
    tst INTEGER,
    tid VARCHAR(255),
    conn VARCHAR(1),
    inregions TEXT[],
    inrids TEXT[],
    SSID VARCHAR(255),
    created_at INTEGER,
    m INTEGER,
    dt DATE,
    dtts TIMESTAMP,
    id VARCHAR(255),
    PRIMARY KEY (rider_id,order_number, tst)
);
-- drop table


CREATE INDEX IF NOT EXISTS idx_rider_location_tst_desc ON rider_location (tst DESC);
CREATE INDEX IF NOT EXISTS idx_rider_location_dtts_desc ON rider_location (dtts DESC);

-- Create location_event table
CREATE TABLE IF NOT EXISTS rider_location_event (
    topic VARCHAR(255) PRIMARY KEY,
    rider_id VARCHAR(100) NOT NULL,
    order_number VARCHAR(100) NOT NULL,
    res_enter_dtts TIMESTAMP,
    res_leave_dtts TIMESTAMP,
    cust_enter_dtts TIMESTAMP,
    cust_leave_dtts TIMESTAMP,
    tst BIGINT NOT NULL,
    dt DATE,
    dtts TIMESTAMP
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_rider_location_event_rider_id ON rider_location_event(rider_id);
CREATE INDEX IF NOT EXISTS idx_rider_location_event_order_number ON rider_location_event(order_number);
CREATE INDEX IF NOT EXISTS idx_rider_location_event_tst ON rider_location_event(tst);
CREATE INDEX IF NOT EXISTS idx_rider_location_event_dt ON rider_location_event(dt);


-- # Create a trigger on an update to table rider_location_event
CREATE OR REPLACE FUNCTION public.rider_location_event_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  webhook_payload json;
  changed_fields json;
BEGIN
  -- Create an object containing only the fields that have changed
  changed_fields := json_object_agg(key, value)
  FROM json_each(row_to_json(NEW))
  WHERE CASE 
    WHEN key = 'updated_at' THEN false  -- exclude updated_at from comparison
    ELSE json_extract_path_text(row_to_json(OLD), key) IS DISTINCT FROM json_extract_path_text(row_to_json(NEW), key)
  END;

  -- Build the webhook payload with both complete record and changed fields
  webhook_payload := json_build_object(
    'location_event_new', row_to_json(NEW),
    'changed_fields', changed_fields
  );

  -- Make the HTTP POST request and ignore the response
  PERFORM http_post(
    'https://live-track.byteloop.ai/location-hooks/notify-rider-location-event', 
    webhook_payload::text,
    'application/json'
  );

  RETURN NEW;
END;
$$;


CREATE TRIGGER trigger_rider_location_event_update
    AFTER INSERT OR UPDATE ON rider_location_event
    FOR EACH ROW
    EXECUTE PROCEDURE rider_location_event_update();

-- cleanup
drop trigger if exists trigger_rider_location_event_update on rider_location_event;
drop function if exists rider_location_event_update();