-- =============================================================================================
-- ordelo_datamodels/ordering/web_session_meta.sql
-- Web checkout draft per browser session (restaurant, mode, town, address), two-hour expiry.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  web_session_meta
--                   One row per web checkout session, keyed by its thread_id; holds the editable checkout draft until the order is created.
-- REQUIRES      restaurant-agents: thread
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
-- CALLED BY     web_session_meta:
--                 python    utils_common/web_ordering/lifecycle.py: sweep()
--                 python    utils_common/web_ordering/web_checkout.py: address(), session(), start()
-- PYTHON MODEL  none
-- SECURITY      web_session_meta: RLS ON; service role only (anon/authenticated revoked)
-- TESTS         none
-- GOTCHAS       postcode is checked by the NOT VALID constraint web_session_meta_postcode_format: new and updated rows only.
--               cust_id is the synthetic W-key of the checkout; each created order gets a fresh recipient W-key (see docs).
--               Captured from live on 2026-10-16; first created by migrations/ordelo_agg_r3.sql (history).
-- SEE ALSO      docs/web-ordering-playground.md
--               docs/web-ordering-architecture.html
--               ordering/create_food_order_with_items.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table web_session_meta
--   One row per web checkout session, keyed by its thread_id; holds the editable checkout draft until the order is created.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.web_session_meta (
    thread_id text NOT NULL,
    visitor_id text NOT NULL,
    cust_id text NOT NULL,
    rest_ref character varying(4) NOT NULL,
    mode text NOT NULL,
    town_slug text NOT NULL,
    postcode_district text,
    device_class text,
    utm jsonb NOT NULL DEFAULT '{}' ::jsonb,
    referrer_host text,
    address jsonb,
    expires_at timestamp with time zone NOT NULL DEFAULT (now() + '02:00:00'::interval),
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    postcode text,
    CONSTRAINT web_session_meta_pkey PRIMARY KEY (thread_id),
    CONSTRAINT web_session_meta_cust_id_key UNIQUE (cust_id),
    CONSTRAINT web_session_meta_mode_check CHECK ((mode = ANY (ARRAY['delivery'::text, 'collection'::text]))),
    CONSTRAINT web_session_meta_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES thread (thread_id)
);

ALTER TABLE public.web_session_meta
    DROP CONSTRAINT IF EXISTS web_session_meta_postcode_format;

ALTER TABLE public.web_session_meta
    ADD CONSTRAINT web_session_meta_postcode_format CHECK (((postcode IS NULL) OR (postcode ~ '^[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}$'::text))) NOT VALID;

ALTER TABLE public.web_session_meta ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.web_session_meta FROM anon, authenticated;

COMMENT ON COLUMN public.web_session_meta.postcode IS 'Full delivery postcode approved at checkout start (ADR 0008). Authority for the postcode-sector gate in web_checkout.address().';

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.web_session_meta IS 'One row per web checkout session, keyed by its thread_id; holds the editable checkout draft until the order is created.';
