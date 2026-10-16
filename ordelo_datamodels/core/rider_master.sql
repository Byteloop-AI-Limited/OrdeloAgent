CREATE TABLE IF NOT EXISTS public.rider_master (
    id serial NOT NULL,
    rider_id character varying(12),
    rider_name text NOT NULL,
    vehicle_type character varying(15) NOT NULL,
    town character varying(255) NOT NULL,
    status character varying(50) NOT NULL,
    is_in_shift boolean NOT NULL DEFAULT true,
    priority integer NOT NULL DEFAULT 1,
    dtts timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    shift_response_dtts timestamp without time zone, -- added by core/restaurant_master.sql
    CONSTRAINT rider_master_pkey PRIMARY KEY (id)
);
