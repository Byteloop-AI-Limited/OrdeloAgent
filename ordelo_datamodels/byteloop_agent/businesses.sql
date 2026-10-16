-- =============================================================================================
-- ordelo_datamodels/byteloop_agent/businesses.sql
-- Businesses known to the Byteloop agent (slug, name, JSON config).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  businesses
--                   One business: unique slug, name, JSON config and active flag.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   ordelo/agents/byteloop_agent.py looks a business up by slug and uses its config. Unrelated to restaurant ordering.
-- LIFECYCLE     none
-- CALLED BY     businesses:
--                 python    ordelo/agents/byteloop_agent.py: prompt()
-- PYTHON MODEL  none
-- SECURITY      businesses: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         none
-- GOTCHAS       Captured from live on 2026-10-16; it had no file in the repo.
-- SEE ALSO      byteloop_agent/documents.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table businesses
--   One business: unique slug, name, JSON config and active flag.
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.businesses IS 'One business: unique slug, name, JSON config and active flag.';
