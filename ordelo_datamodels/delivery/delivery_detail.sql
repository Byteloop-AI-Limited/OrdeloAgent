CREATE TABLE IF NOT EXISTS public.delivery_detail (
    order_number character varying(100) NOT NULL,
    customer_id character varying(12) NOT NULL,
    vehicle_type character varying(15) NOT NULL,
    town character varying(255) NOT NULL,
    rider_payout double precision NOT NULL,
    distance double precision NOT NULL,
    status character varying(50) NOT NULL,
    dispatch_id integer,
    rider_id character varying(12),
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT delivery_detail_pkey1 PRIMARY KEY (order_number, vehicle_type),
    CONSTRAINT delivery_detail_status_check1 CHECK (((status)::text = ANY ((ARRAY['unassigned'::character varying, 'assigned'::character varying, 'vehicle_type_timedout'::character varying, 'completed'::character varying])::text[])))
);
