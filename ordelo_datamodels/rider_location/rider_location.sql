-- Updated DDL statement for the delivery_inflight_location_events table with all fields
CREATE TABLE IF NOT EXISTS public.rider_location (
    topic character varying(255),
    rider_id character varying(12),
    customer_id character varying(12),
    order_number character varying(100),
    acc integer,
    alt integer,
    batt integer,
    lat double precision NOT NULL,
    lon double precision NOT NULL,
    tst integer,
    tid character varying(255),
    conn character varying(1),
    inregions text[],
    inrids text[],
    created_at integer,
    m integer,
    tst_dtts timestamp without time zone,
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- drop table
-- CREATE INDEX IF NOT EXISTS idx_rider_location_tst_desc ON rider_location (tst DESC);

-- CREATE INDEX IF NOT EXISTS idx_rider_location_dtts_desc ON rider_location (dtts DESC);
