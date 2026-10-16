CREATE TABLE IF NOT EXISTS public.customer_master (
    cust_id character varying(12) NOT NULL,
    cust_name text,
    cust_email text,
    house_number text,
    building_name text,
    street_name text,
    city text,
    postcode text,
    lat double precision,
    lon double precision,
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT customer_master_pkey PRIMARY KEY (cust_id)
);
