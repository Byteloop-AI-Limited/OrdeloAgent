-- =============================================================================================
-- ordelo_datamodels/core/customer_master.sql
-- One row per customer: id (phone or web W-key), name and delivery address with coordinates.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  customer_master
--                   Customer identity and address. cust_id is a phone number (WhatsApp) or a W-key (web; one per order).
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none (DDL only)
-- HOW IT FITS   init_delivery() and init_takeaway() read the customer's name and address from here to build the order summary.
--                 WhatsApp customers are keyed by phone; web checkout creates a fresh 'W...' key per order
--                 (utils_common/web_ordering/web_checkout.py) so each order keeps the address it was placed with.
--                 cust_rest_map links a customer to the restaurants they consented to.
-- LIFECYCLE     Upserted by the customer address flows (watomation/routers/customer_hooks.py, WhatsApp flows) and by web checkout.
-- CALLED BY     customer_master:
--                 sql       init_delivery(), init_takeaway(), insert_delivery_detail()
--                 python    utils_common/order_management/food_order_pymodel.py: FoodOrder.update_final_order_value_in_db()
--                 python    utils_common/web_ordering/web_checkout.py: create()
--                 python    watomation/routers/customer_hooks.py: create_or_update_customer(), update_address()
--                 python    watomation/routers/order_hooks.py: capture_address()
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/rest_agent/agents/delivery.py
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/services/ordelo_service/datamodels/customer_master_pymodel.py
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/services/ordelo_service/ordelo_service.py
--                 r-agents  restaurant-agents/tests/legacy_contract/rest_agent/test_delivery_agent.py
--                 r-agents  restaurant-agents/tests/services/ordelo_service/test_datamodels.py
-- PYTHON MODEL  ordelo_datamodels/customer_master_pymodel.py CustomerMaster
-- SECURITY      customer_master: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         tests/ordelo_datamodels/test_master_pymodels.py
--               tests/utils_common/order_management/test_food_order_pymodel.py
--               tests/watomation/routers/test_customer_hooks.py
--               tests/watomation/routers/test_order_hooks.py
--               tests/watomation/test_customer_notification_contracts.py
-- GOTCHAS       RLS is off and anon has default grants on personal data: see docs/to-do.md (security review).
-- SEE ALSO      core/cust_rest_map.sql
--               delivery/init_delivery.sql
--               docs/web-ordering-playground.md (identity)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table customer_master
--   Customer identity and address. cust_id is a phone number (WhatsApp) or a W-key (web; one per order).
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.customer_master (
    cust_id character varying(12) NOT NULL,
    cust_name text,
    cust_email text,
    house_number text,
    building_name text,
    street_name text,
    city text,
    postcode text,
    lat double precision,
    lon double precision,
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT customer_master_pkey PRIMARY KEY (cust_id)
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.customer_master IS 'Customer identity and address. cust_id is a phone number (WhatsApp) or a W-key (web; one per order).';
