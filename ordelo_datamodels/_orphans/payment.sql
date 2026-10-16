CREATE TABLE IF NOT EXISTS public.payment_details (
    order_number character varying(100) NOT NULL,
    payment_id text,
    CONSTRAINT payment_details_pkey PRIMARY KEY (order_number)
);
