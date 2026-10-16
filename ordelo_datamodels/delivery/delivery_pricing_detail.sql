-- =============================================================================================
-- ordelo_datamodels/delivery/delivery_pricing_detail.sql
-- Per-order pricing summary (distance, minimum order value, message) that delivery_option rows hang off.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  delivery_pricing_detail
--                   Pricing header for an order: distance, minimum order value and the customer-facing message.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   Parent of delivery_option (FK). Written by the pricing microservice (no writer in the three repos), read by the
--                 WhatsApp handler for the pricing message (watomation/on_message_wa_handler.py).
-- LIFECYCLE     none
-- CALLED BY     delivery_pricing_detail:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      delivery_pricing_detail: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         none
-- GOTCHAS       none
-- SEE ALSO      delivery/delivery_option.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table delivery_pricing_detail
--   Pricing header for an order: distance, minimum order value and the customer-facing message.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.delivery_pricing_detail (
    order_number character varying(100) NOT NULL,
    distance double precision NOT NULL,
    message text,
    minimum_order_value numeric(10, 2) DEFAULT NULL::numeric,
    CONSTRAINT delivery_pricing_detail_pkey PRIMARY KEY (order_number)
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.delivery_pricing_detail IS 'Pricing header for an order: distance, minimum order value and the customer-facing message.';

-- -- Show table schema
-- SELECT
--     table_name,
--     column_name,
--     data_type,
--     is_nullable
-- FROM
--     information_schema.columns
-- WHERE
--     table_name = 'delivery_detail';
