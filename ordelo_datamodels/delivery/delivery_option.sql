CREATE TABLE IF NOT EXISTS public.delivery_option (
    id serial NOT NULL,
    order_number character varying(100),
    vehicle_type character varying(50),
    rank integer,
    final_order_value double precision,
    total_customer_charge double precision,
    rest_cost double precision,
    driver_payout double precision,
    byteloop_commission_percentage double precision,
    byteloop_commission_fee double precision,
    breakdown jsonb,
    message text,
    minimum_order_value double precision NOT NULL DEFAULT 0.0,
    CONSTRAINT delivery_option_pkey PRIMARY KEY (id),
    CONSTRAINT delivery_option_order_number_fkey FOREIGN KEY (order_number) REFERENCES delivery_pricing_detail(order_number)
);

-- change driver_payout to rider_payout
