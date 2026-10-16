CREATE TABLE IF NOT EXISTS public.businesses (
    id uuid NOT NULL DEFAULT gen_random_uuid (),
    slug character varying(100) NOT NULL,
    name character varying(255) NOT NULL,
    config jsonb NOT NULL DEFAULT '{}' ::jsonb,
    is_active boolean DEFAULT TRUE,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT businesses_pkey PRIMARY KEY (id),
    CONSTRAINT businesses_slug_key UNIQUE (slug)
);
