CREATE TABLE IF NOT EXISTS public.web_rate_limit (
    identity_hash text NOT NULL,
    window_start timestamp with time zone NOT NULL,
    attempts integer NOT NULL DEFAULT 1,
    CONSTRAINT web_rate_limit_pkey PRIMARY KEY (identity_hash, window_start)
);

ALTER TABLE public.web_rate_limit ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.web_rate_limit FROM anon, authenticated;
