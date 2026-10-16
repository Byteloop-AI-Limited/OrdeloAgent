-- =============================================================================================
-- ordelo_datamodels/_orphans/core.sql
-- Unused live table from the menu area.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16). Orphan candidates: live, no caller found.
-- OBJECTS       table  elas_menu_before_march
--                   Snapshot of the ELAS menu taken before March 2026 (81 rows, never updated).
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
-- CALLED BY     elas_menu_before_march:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      elas_menu_before_march: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         none
-- GOTCHAS       none
-- SEE ALSO      docs/to-do.md (decide on orphan candidates)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table elas_menu_before_march
--   Snapshot of the ELAS menu taken before March 2026 (81 rows, never updated).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.elas_menu_before_march (
    id bigint,
    created_at timestamp with time zone,
    title text,
    description text,
    availability text,
    price numeric,
    currency text,
    branch_link text,
    image_link text,
    branch_name text,
    category text,
    discounted_price text,
    sub_category text,
    addons jsonb,
    sub_category_description text,
    dietary_requirements text
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.elas_menu_before_march IS 'Snapshot of the ELAS menu taken before March 2026 (81 rows, never updated).';
