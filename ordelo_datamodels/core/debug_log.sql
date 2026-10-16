CREATE TABLE IF NOT EXISTS public.debug_log (
    id serial NOT NULL,
    trigger_name text,
    order_number text,
    message text,
    payload jsonb,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT debug_log_pkey PRIMARY KEY (id)
);
