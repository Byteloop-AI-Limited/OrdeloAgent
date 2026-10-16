-- =============================================================================================
-- ordelo_datamodels/core/waba_es.sql
-- WhatsApp Business embedded-signup events for restaurants connecting their own WhatsApp number.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  waba_es
--                   One row per WhatsApp embedded-signup event (ids, auth code, business token).
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none (DDL only)
-- HOW IT FITS   utils_common/waba_es/onboarding_utils.py stores each embedded-signup callback (phone number id, WABA id,
--                 business id, auth code, business token). business_ref ties the row to a restaurant. Read back during onboarding;
--                 see utils_common/waba_es/embedded_signup_guide.md.
-- LIFECYCLE     one row per signup event; not updated by code.
-- CALLED BY     waba_es:
--                 python    utils_common/waba_es/onboarding_utils.py: onboard_business_customer()
--                 python    watomation/routers/temp_nb.py (module-level SQL)
-- PYTHON MODEL  none
-- SECURITY      waba_es: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         none
-- GOTCHAS       business_token is a credential stored in clear text with RLS off: part of the security review (docs/to-do.md).
-- SEE ALSO      utils_common/waba_es/embedded_signup_guide.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table waba_es
--   One row per WhatsApp embedded-signup event (ids, auth code, business token).
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.waba_es IS 'One row per WhatsApp embedded-signup event (ids, auth code, business token).';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- Backward-compatible migration for existing deployments
-- ALTER TABLE IF EXISTS waba_es
--   ADD COLUMN IF NOT EXISTS phone_num TEXT;
-- select * from waba_es order by dtts desc;

-- update waba_es set business_ref='sfcs' where id = 5;

-- drop table waba_es;
