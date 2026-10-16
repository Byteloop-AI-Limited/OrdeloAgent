CREATE TABLE IF NOT EXISTS public.driver_location_event (
    id serial NOT NULL,
    topic character varying(255) NOT NULL,
    driver_id character varying(100) NOT NULL,
    order_number character varying(100) NOT NULL,
    event character varying(10) NOT NULL,
    rid character varying(100) NOT NULL,
    description text NOT NULL,
    tst bigint NOT NULL,
    lat double precision,
    lon double precision,
    dt date,
    dtts timestamp without time zone,
    CONSTRAINT driver_location_event_pkey PRIMARY KEY (id),
    CONSTRAINT driver_location_event_event_check CHECK (((event)::text = ANY ((ARRAY['enter'::character varying, 'leave'::character varying])::text[])))
);
