-- =============================================================================================
-- ordelo_datamodels/platform/app_url.sql
-- Legacy single-row table holding an application URL (config_value).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  app_url
--                   One config_value row with an application URL (legacy; prefer ordelo_config).
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   Read by watomation/fapp_ordelo_agent.py and restaurant-agents' operational lookup cache. ordelo_config is the
--                 current home for URLs (ORDELO_APP_URL, <REST>_APP_URL).
-- LIFECYCLE     none
-- CALLED BY     app_url:
--                 python    watomation/fapp_ordelo_agent.py: reset_restaurant_base_url_cache_endpoint()
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/services/operational_lookup_cache.py
-- PYTHON MODEL  none
-- SECURITY      app_url: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         none
-- GOTCHAS       Captured from live on 2026-10-16; it had no file in the repo.
-- SEE ALSO      core/ordelo_config.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table app_url
--   One config_value row with an application URL (legacy; prefer ordelo_config).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.app_url (
    config_value text
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.app_url IS 'One config_value row with an application URL (legacy; prefer ordelo_config).';
