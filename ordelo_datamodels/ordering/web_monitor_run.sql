-- =============================================================================================
-- ordelo_datamodels/ordering/web_monitor_run.sql
-- One row per day: the daily web price/order audit claim, completion and flagged orders.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  web_monitor_run
--                   Daily audit ledger: the first worker to claim run_day runs the audit; alert_orders lists what it flagged.
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
-- CALLED BY     web_monitor_run:
--                 python    utils_common/web_ordering/monitoring.py: sweep()
-- PYTHON MODEL  none
-- SECURITY      web_monitor_run: RLS ON; service role only (anon/authenticated revoked)
-- TESTS         tests/utils_common/web_ordering/test_web_contract.py
-- GOTCHAS       Captured from live on 2026-10-16; first created by migrations/ordelo_agg_r3.sql (history).
-- SEE ALSO      docs/web-ordering-playground.md
--               docs/web-ordering-architecture.html
--               ordering/create_food_order_with_items.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table web_monitor_run
--   Daily audit ledger: the first worker to claim run_day runs the audit; alert_orders lists what it flagged.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.web_monitor_run (
    run_day date NOT NULL,
    completed_at timestamp with time zone,
    alert_orders text[] NOT NULL DEFAULT '{}' ::text[],
    CONSTRAINT web_monitor_run_pkey PRIMARY KEY (run_day)
);

ALTER TABLE public.web_monitor_run ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.web_monitor_run FROM anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.web_monitor_run IS 'Daily audit ledger: the first worker to claim run_day runs the audit; alert_orders lists what it flagged.';
