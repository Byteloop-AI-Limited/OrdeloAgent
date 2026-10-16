-- =============================================================================================
-- ordelo_datamodels/ordering/web_rate_limit.sql
-- Hourly counter of web session creations per trusted client-identity hash.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  web_rate_limit
--                   Rate-limit counter: attempts per (identity_hash, window_start); the router increments, lifecycle prunes old windows.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   Web checkout (restaurant-frontend -> OrdeloAgent /web routes, utils_common/web_ordering/*):
--                 start   -> thread (agent 'WEB') + web_session_meta (the editable checkout draft, 2 h)
--                 create  -> web_order_request (idempotency: same key + body returns the same order) -> food_order
--                 page    -> order_access_grant (hash of the secret in the order-tracking link)
--                 payment -> payment_event; a cancelled/late payment is retried through web_payment_release
--                 limits  -> web_rate_limit (hourly session-create counter); daily audit -> web_monitor_run
--                 All six tables are server-only (RLS on, anon/authenticated revoked) and reached with client_ordelo_service.
-- LIFECYCLE     see docs/web-ordering-playground.md (Tables section) for who writes and reads each column.
-- CALLED BY     web_rate_limit:
--                 python    utils_common/web_ordering/lifecycle.py: sweep()
--                 python    watomation/routers/web_hooks.py: start()
-- PYTHON MODEL  none
-- SECURITY      web_rate_limit: RLS ON; service role only (anon/authenticated revoked)
-- TESTS         none
-- GOTCHAS       Captured from live on 2026-10-16; first created by migrations/ordelo_agg_r3.sql (history).
-- SEE ALSO      docs/web-ordering-playground.md
--               docs/web-ordering-architecture.html
--               ordering/create_food_order_with_items.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table web_rate_limit
--   Rate-limit counter: attempts per (identity_hash, window_start); the router increments, lifecycle prunes old windows.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.web_rate_limit (
    identity_hash text NOT NULL,
    window_start timestamp with time zone NOT NULL,
    attempts integer NOT NULL DEFAULT 1,
    CONSTRAINT web_rate_limit_pkey PRIMARY KEY (identity_hash, window_start)
);

ALTER TABLE public.web_rate_limit ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.web_rate_limit FROM anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.web_rate_limit IS 'Rate-limit counter: attempts per (identity_hash, window_start); the router increments, lifecycle prunes old windows.';
