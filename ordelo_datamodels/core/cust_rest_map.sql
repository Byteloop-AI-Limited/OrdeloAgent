-- Customer restaurant mapping
CREATE TABLE IF NOT EXISTS public.cust_rest_map (
    cust_id character varying(12) NOT NULL,
    rest_ref character varying(4) NOT NULL,
    has_consent boolean NOT NULL DEFAULT false,
    consent_dtts timestamp with time zone,
    dtts timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT cust_rest_map_pkey PRIMARY KEY (cust_id, rest_ref),
    CONSTRAINT cust_rest_map_cust_id_fkey FOREIGN KEY (cust_id) REFERENCES customer_master(cust_id),
    CONSTRAINT cust_rest_map_rest_ref_fkey FOREIGN KEY (rest_ref) REFERENCES restaurant_master(rest_ref)
);
