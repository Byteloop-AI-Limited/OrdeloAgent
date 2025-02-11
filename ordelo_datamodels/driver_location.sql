
-- Updated DDL statement for the delivery_inflight_location_events table with all fields
CREATE TABLE IF NOT EXISTS driver_location (
    topic VARCHAR(255),
    driver_id VARCHAR(25),
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
    PRIMARY KEY (driver_id,order_number, tst)
) WITH (OIDS=FALSE);

CREATE INDEX IF NOT EXISTS idx_driver_location_tst_desc ON driver_location (tst DESC);
CREATE INDEX IF NOT EXISTS idx_driver_location_dtts_desc ON driver_location (dtts DESC);

-- Create location_event table
CREATE TABLE IF NOT EXISTS driver_location_event (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(255) NOT NULL,
    driver_id VARCHAR(100) NOT NULL,
    order_number VARCHAR(100) NOT NULL,
    event VARCHAR(10) NOT NULL CHECK (event IN ('enter', 'leave')),
    rid VARCHAR(100) NOT NULL,
    description TEXT NOT NULL,
    tst BIGINT NOT NULL,
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    dt DATE,
    dtts TIMESTAMP
) WITH (OIDS=FALSE);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_location_event_driver_id ON location_event(driver_id);
CREATE INDEX IF NOT EXISTS idx_location_event_order_number ON location_event(order_number);
CREATE INDEX IF NOT EXISTS idx_location_event_tst ON location_event(tst);
CREATE INDEX IF NOT EXISTS idx_location_event_dt ON location_event(dt);



-- Getting distance between two locations
select ST_DistanceSphere(
    ST_MakePoint(0.10458276590699943, 51.361073759134904), 
    ST_MakePoint(0.1311044466965276, 51.35850119532111)
    );