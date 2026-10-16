-- =============================================================================================
-- ordelo_datamodels/_orphans/byteloop_agent.sql
-- Unused live table from the Byteloop agent area.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16). Orphan candidates: live, no caller found.
-- OBJECTS       table  elaivec
--                   Empty vector table (no rows ever written).
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none when applied. Functions that make HTTP calls or change rows only do so if someone calls them.
-- HOW IT FITS   Orphan candidates (Gate 1 decision D1): objects that exist on live but that nothing calls. A search on 2026-10-16 found
--                 no reference in OrdeloAgent, restaurant-frontend or restaurant-agents code, in any other live function or view, in a
--                 trigger or in a pg_cron job. They are captured here exactly as live so the repo describes the whole database.
--                 Nothing has been dropped: deciding keep or drop is an owner decision (docs/to-do.md). Before dropping one, re-check
--                 for callers outside these three repos (other services, manual scripts, Supabase Studio).
-- LIFECYCLE     none
-- CALLED BY     elaivec:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      elaivec: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         none
-- GOTCHAS       none
-- SEE ALSO      docs/to-do.md (decide on orphan candidates)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table elaivec
--   Empty vector table (no rows ever written).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.elaivec (
    id uuid NOT NULL,
    content text,
    metadata jsonb,
    embedding vector (1536),
    CONSTRAINT elaivec_pkey PRIMARY KEY (id)
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.elaivec IS 'Empty vector table (no rows ever written).';
