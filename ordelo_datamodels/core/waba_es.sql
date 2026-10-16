CREATE TABLE IF NOT EXISTS public.waba_es (
    id bigserial NOT NULL,
    phone_num text, -- display phone number as string
    business_ref text, -- business reference[]
    waba_id bigint,
    phone_number_id bigint,
    business_id bigint,
    event_type text, -- e.g., WA_EMBEDDED_SIGNUP, FB_AUTH_RESPONSE (value comes from event payload)
    code text, -- FB auth code
    business_token text, -- Sensitive: consider encrypting or restricting access
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT waba_es_pkey PRIMARY KEY (id)
);

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- Backward-compatible migration for existing deployments
-- ALTER TABLE IF EXISTS waba_es
--   ADD COLUMN IF NOT EXISTS phone_num TEXT;
-- select * from waba_es order by dtts desc;

-- update waba_es set business_ref='sfcs' where id = 5;

-- drop table waba_es;
