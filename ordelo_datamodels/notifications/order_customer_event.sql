CREATE TABLE IF NOT EXISTS public.order_customer_event (
    id bigserial NOT NULL,
    order_number text NOT NULL,
    event_key text NOT NULL, -- deterministic, e.g. 'payment_authorised', 'rider_assigned:<dispatch_id>'
    event_type text NOT NULL, -- plan §7.4
    occurred_at timestamp with time zone NOT NULL DEFAULT now(),
    is_estimate boolean NOT NULL DEFAULT false,
    data jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT order_customer_event_pkey PRIMARY KEY (id),
    CONSTRAINT order_customer_event_key_uq UNIQUE (order_number, event_key),
    CONSTRAINT order_customer_event_order_number_fkey FOREIGN KEY (order_number) REFERENCES food_order(order_number) ON DELETE CASCADE
);
