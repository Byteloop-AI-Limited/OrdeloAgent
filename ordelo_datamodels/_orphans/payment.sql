-- =============================================================================================
-- ordelo_datamodels/_orphans/payment.sql
-- Live payment table with no caller in the three repos.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16). Orphan candidates: live, no caller found.
-- OBJECTS       table  payment_details
--                   Payment records (about 750 rows; written until at least September 2026) by something outside these repos.
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
-- CALLED BY     payment_details:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      payment_details: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         none
-- GOTCHAS       Rows were still being written in September 2026: check the payment microservice before treating it as unused.
-- SEE ALSO      docs/to-do.md
--               .claude/skills/ordelo-local-automatic-orders/scripts/inspect_order.py (reads it for investigations)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table payment_details
--   Payment records (about 750 rows; written until at least September 2026) by something outside these repos.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.payment_details (
    order_number character varying(100) NOT NULL,
    payment_id text,
    CONSTRAINT payment_details_pkey PRIMARY KEY (order_number)
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.payment_details IS 'Payment records (about 750 rows; written until at least September 2026) by something outside these repos.';
