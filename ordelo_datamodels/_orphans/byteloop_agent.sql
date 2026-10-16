CREATE TABLE IF NOT EXISTS public.elaivec (
    id uuid NOT NULL,
    content text,
    metadata jsonb,
    embedding vector(1536),
    CONSTRAINT elaivec_pkey PRIMARY KEY (id)
);
