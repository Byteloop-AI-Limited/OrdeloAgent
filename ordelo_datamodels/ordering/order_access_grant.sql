-- =============================================================================================
-- ordelo_datamodels/ordering/order_access_grant.sql
-- Hashed secrets behind order-tracking links (page tokens), with detail level and expiry.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  order_access_grant
--                   Hash-only secret for an order-tracking link; verified on every page view (utils_common/web_ordering/order_access.py).
-- REQUIRES      restaurant-agents: food_order
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
-- CALLED BY     order_access_grant:
--                 python    utils_common/web_ordering/order_access.py: issue(), issue_for_whatsapp(), verify()
-- PYTHON MODEL  none
-- SECURITY      order_access_grant: RLS ON; service role only (anon/authenticated revoked)
-- TESTS         none
-- GOTCHAS       kind 'wa_handoff' is allowed by the schema but current code only issues 'page_token'.
--               Captured from live on 2026-10-16; first created by migrations/ordelo_agg_r3.sql (history).
-- SEE ALSO      docs/web-ordering-playground.md
--               docs/web-ordering-architecture.html
--               ordering/create_food_order_with_items.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table order_access_grant
--   Hash-only secret for an order-tracking link; verified on every page view (utils_common/web_ordering/order_access.py).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.order_access_grant (
    id bigserial NOT NULL,
    order_number text NOT NULL,
    kind text NOT NULL,
    secret_hash bytea NOT NULL,
    detail_level text NOT NULL DEFAULT 'full' ::text,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    consumed_by text,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT order_access_grant_pkey PRIMARY KEY (id),
    CONSTRAINT order_access_grant_secret_hash_key UNIQUE (secret_hash),
    CONSTRAINT order_access_grant_kind_check CHECK ((kind = ANY (ARRAY['page_token'::text, 'wa_handoff'::text]))),
    CONSTRAINT order_access_grant_order_number_fkey FOREIGN KEY (order_number) REFERENCES food_order (order_number)
);

ALTER TABLE public.order_access_grant ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.order_access_grant FROM anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.order_access_grant IS 'Hash-only secret for an order-tracking link; verified on every page view (utils_common/web_ordering/order_access.py).';
