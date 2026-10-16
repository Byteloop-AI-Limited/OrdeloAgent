-- =============================================================================================
-- ordelo_datamodels/core/cust_rest_map.sql
-- Which customers have consented to which restaurants.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  cust_rest_map
--                   Customer-to-restaurant link with consent flag and time.
-- REQUIRES      core/customer_master.sql
--               core/restaurant_master.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none (DDL only)
-- HOW IT FITS   One row per (customer, restaurant). has_consent / consent_dtts record the marketing/updates consent captured in the
--                 WhatsApp flows (watomation/routers/customer_hooks.py, order_hooks.py). Foreign keys to customer_master and
--                 restaurant_master.
-- LIFECYCLE     Upserted when a customer orders from or consents to a restaurant; never deleted by code.
-- CALLED BY     cust_rest_map:
--                 python    watomation/routers/customer_hooks.py: update_cust_rest_map()
--                 python    watomation/routers/order_hooks.py (module-level SQL)
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/services/ordelo_service/datamodels/cust_rest_map_pymodel.py
--                 r-agents  restaurant-agents/tests/services/ordelo_service/test_datamodels.py
-- PYTHON MODEL  ordelo_datamodels/cust_rest_map_pymodel.py CustRestMap
-- SECURITY      cust_rest_map: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         tests/ordelo_datamodels/test_master_pymodels.py
-- GOTCHAS       none
-- SEE ALSO      core/customer_master.sql
--               core/restaurant_master.sql
--               migrations/create_cust_rest_map.sql (history)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table cust_rest_map
--   Customer-to-restaurant link with consent flag and time.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.cust_rest_map (
    cust_id character varying(12) NOT NULL,
    rest_ref character varying(4) NOT NULL,
    has_consent boolean NOT NULL DEFAULT FALSE,
    consent_dtts timestamp with time zone,
    dtts timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT cust_rest_map_pkey PRIMARY KEY (cust_id, rest_ref),
    CONSTRAINT cust_rest_map_cust_id_fkey FOREIGN KEY (cust_id) REFERENCES customer_master (cust_id),
    CONSTRAINT cust_rest_map_rest_ref_fkey FOREIGN KEY (rest_ref) REFERENCES restaurant_master (rest_ref)
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.cust_rest_map IS 'Customer-to-restaurant link with consent flag and time.';
