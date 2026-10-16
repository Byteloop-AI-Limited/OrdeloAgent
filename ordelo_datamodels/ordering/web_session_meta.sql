CREATE TABLE IF NOT EXISTS public.web_session_meta (
    thread_id text NOT NULL,
    visitor_id text NOT NULL,
    cust_id text NOT NULL,
    rest_ref character varying(4) NOT NULL,
    mode text NOT NULL,
    town_slug text NOT NULL,
    postcode_district text,
    device_class text,
    utm jsonb NOT NULL DEFAULT '{}'::jsonb,
    referrer_host text,
    address jsonb,
    expires_at timestamp with time zone NOT NULL DEFAULT (now() + '02:00:00'::interval),
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    postcode text,
    CONSTRAINT web_session_meta_pkey PRIMARY KEY (thread_id),
    CONSTRAINT web_session_meta_cust_id_key UNIQUE (cust_id),
    CONSTRAINT web_session_meta_mode_check CHECK ((mode = ANY (ARRAY['delivery'::text, 'collection'::text]))),
    CONSTRAINT web_session_meta_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES thread(thread_id)
);

-- web_session_meta_postcode_format is NOT VALID on live: it checks new and updated rows only; older rows were never validated.
ALTER TABLE public.web_session_meta DROP CONSTRAINT IF EXISTS web_session_meta_postcode_format;
ALTER TABLE public.web_session_meta ADD CONSTRAINT web_session_meta_postcode_format CHECK (((postcode IS NULL) OR (postcode ~ '^[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}$'::text))) NOT VALID;

ALTER TABLE public.web_session_meta ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.web_session_meta FROM anon, authenticated;

COMMENT ON COLUMN public.web_session_meta.postcode IS 'Full delivery postcode approved at checkout start (ADR 0008). Authority for the postcode-sector gate in web_checkout.address().';
