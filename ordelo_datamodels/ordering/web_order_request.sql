CREATE TABLE IF NOT EXISTS public.web_order_request (
    idempotency_key text NOT NULL,
    thread_id text NOT NULL,
    body_hash text NOT NULL,
    order_number text NOT NULL,
    address jsonb,
    quote jsonb,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT web_order_request_pkey PRIMARY KEY (idempotency_key),
    CONSTRAINT web_order_request_order_number_key UNIQUE (order_number),
    CONSTRAINT web_order_request_order_number_fkey FOREIGN KEY (order_number) REFERENCES food_order(order_number),
    CONSTRAINT web_order_request_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES thread(thread_id)
);

ALTER TABLE public.web_order_request ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.web_order_request FROM anon, authenticated;
