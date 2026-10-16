CREATE TABLE IF NOT EXISTS public.order_access_grant (
    id bigserial NOT NULL,
    order_number text NOT NULL,
    kind text NOT NULL,
    secret_hash bytea NOT NULL,
    detail_level text NOT NULL DEFAULT 'full'::text,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    consumed_by text,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT order_access_grant_pkey PRIMARY KEY (id),
    CONSTRAINT order_access_grant_secret_hash_key UNIQUE (secret_hash),
    CONSTRAINT order_access_grant_kind_check CHECK ((kind = ANY (ARRAY['page_token'::text, 'wa_handoff'::text]))),
    CONSTRAINT order_access_grant_order_number_fkey FOREIGN KEY (order_number) REFERENCES food_order(order_number)
);

ALTER TABLE public.order_access_grant ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.order_access_grant FROM anon, authenticated;
