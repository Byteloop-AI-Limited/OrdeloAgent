-- =============================================================================================
-- ordelo_datamodels/delivery/delivery_option.sql
-- Priced delivery options per order (one row per vehicle type, ranked), from the pricing service.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  delivery_option
--                   Price breakdown for one vehicle type of an order: rank, customer charge, restaurant cost, driver payout, commission.
-- REQUIRES      delivery/delivery_pricing_detail.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   process_delivery() opens delivery_detail rows in delivery_option.rank order (rank 1 first), copying payout and distance.
--                 No writer exists in the three repos: the rows come from the pricing microservice (config/microservices_setting.py
--                 ms_pricing_url), whose 'delivery_options' response the order code reads (utils_common/order_management/order_service.py).
-- LIFECYCLE     written once per quote; read by process_delivery().
-- CALLED BY     delivery_option:
--                 sql       init_delivery_detail(), insert_delivery_detail(), manage_delivery_detail()
--                           overwatch_view(), process_delivery()
-- PYTHON MODEL  none
-- SECURITY      delivery_option: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         none
-- GOTCHAS       The FK points at delivery_pricing_detail(order_number), so the pricing row must exist first.
-- SEE ALSO      delivery/delivery_pricing_detail.sql
--               delivery/process_delivery.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table delivery_option
--   Price breakdown for one vehicle type of an order: rank, customer charge, restaurant cost, driver payout, commission.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.delivery_option (
    id serial NOT NULL,
    order_number character varying(100),
    vehicle_type character varying(50),
    rank integer,
    final_order_value double precision,
    total_customer_charge double precision,
    rest_cost double precision,
    driver_payout double precision,
    byteloop_commission_percentage double precision,
    byteloop_commission_fee double precision,
    breakdown jsonb,
    message text,
    minimum_order_value double precision NOT NULL DEFAULT 0.0,
    CONSTRAINT delivery_option_pkey PRIMARY KEY (id),
    CONSTRAINT delivery_option_order_number_fkey FOREIGN KEY (order_number) REFERENCES delivery_pricing_detail (order_number)
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.delivery_option IS 'Price breakdown for one vehicle type of an order: rank, customer charge, restaurant cost, driver payout, commission.';

-- change driver_payout to rider_payout
