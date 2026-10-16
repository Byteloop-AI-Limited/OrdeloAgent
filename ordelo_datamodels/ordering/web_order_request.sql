-- =============================================================================================
-- ordelo_datamodels/ordering/web_order_request.sql
-- Idempotency record for web create-order: request fingerprint, fixed address copy and cached quote.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  web_order_request
--                   One row per web create-order idempotency key: the same key and body return the same order, a different body is rejected.
-- REQUIRES      restaurant-agents: food_order
--               restaurant-agents: thread
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
-- CALLED BY     web_order_request:
--                 python    ordelo/agents/rider_agent.py: _web_pin_warning()
--                 python    utils_common/web_ordering/customer_order_view.py: get_view()
--                 python    utils_common/web_ordering/web_checkout.py: create()
-- PYTHON MODEL  none
-- SECURITY      web_order_request: RLS ON; service role only (anon/authenticated revoked)
-- TESTS         tests/ordelo/agents/test_rider_agent.py
--               tests/utils_common/web_ordering/test_web_contract.py
-- GOTCHAS       Captured from live on 2026-10-16; first created by migrations/ordelo_agg_r3.sql (history).
-- SEE ALSO      docs/web-ordering-playground.md
--               docs/web-ordering-architecture.html
--               ordering/create_food_order_with_items.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table web_order_request
--   One row per web create-order idempotency key: the same key and body return the same order, a different body is rejected.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.web_order_request (
    idempotency_key text NOT NULL,
    thread_id text NOT NULL,
    body_hash text NOT NULL,
    order_number text NOT NULL,
    address jsonb,
    quote jsonb,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT web_order_request_pkey PRIMARY KEY (idempotency_key),
    CONSTRAINT web_order_request_order_number_key UNIQUE (order_number),
    CONSTRAINT web_order_request_order_number_fkey FOREIGN KEY (order_number) REFERENCES food_order (order_number),
    CONSTRAINT web_order_request_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES thread (thread_id)
);

ALTER TABLE public.web_order_request ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.web_order_request FROM anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.web_order_request IS 'One row per web create-order idempotency key: the same key and body return the same order, a different body is rejected.';
