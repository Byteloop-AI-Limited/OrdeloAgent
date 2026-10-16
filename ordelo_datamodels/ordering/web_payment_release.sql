CREATE TABLE IF NOT EXISTS public.web_payment_release (
    order_number text NOT NULL,
    reason text NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    completed_at timestamp with time zone,
    next_attempt_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT web_payment_release_pkey PRIMARY KEY (order_number),
    CONSTRAINT web_payment_release_order_number_fkey FOREIGN KEY (order_number) REFERENCES food_order(order_number)
);

ALTER TABLE public.web_payment_release ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.web_payment_release FROM anon, authenticated;
