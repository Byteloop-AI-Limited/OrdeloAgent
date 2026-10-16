-- =============================================================================================
-- ordelo_datamodels/test_support/test_reset_takeaway_order.sql
-- Test helper: reset a takeaway order's summary so the restaurant flow can be tested again.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     test_reset_takeaway_order(p_order_number text) -> text
--                   Reset one takeaway order to 'restaurant_unconfirmed' with no pickup time; returns a message.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call sets the order back to 'restaurant_unconfirmed' with no pickup time (the restaurant trigger fires).
-- HOW IT FITS   Developer and operator helpers for live testing. They change real rows, so they are run by hand (or by the WhatsApp
--                 /reset and /test utility commands in watomation/on_message_wa_handler.py), never by the application flow.
--                 See docs/live-order-test-harness.md and test_support/test_restaurant_notices.sql.
-- LIFECYCLE     none
-- CALLED BY     test_reset_takeaway_order:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      test_reset_takeaway_order(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       none
-- SEE ALSO      test_support/test_reset_order_and_dispatch.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function test_reset_takeaway_order(p_order_number text) -> text
--   Reset one takeaway order to 'restaurant_unconfirmed' with no pickup time; returns a message.
--   Data: writes takeaway_summary.
-- ---------------------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS test_reset_takeaway_order (text);

CREATE OR REPLACE FUNCTION test_reset_takeaway_order (p_order_number text)
    RETURNS text
    AS $$
DECLARE
    v_summary_updated integer;
BEGIN
    -- Reset takeaway summary status to restaurant_unconfirmed
    UPDATE
        takeaway_summary
    SET
        status = 'restaurant_unconfirmed',
        restaurant_confirmation_status = 'restaurant_unconfirmed',
        pickup_time = NULL,
        dtts = CURRENT_TIMESTAMP
    WHERE
        order_number = p_order_number;
    GET DIAGNOSTICS v_summary_updated = ROW_COUNT;

    RETURN format('Takeaway order %s reset (summary updated=%s)', p_order_number, v_summary_updated);
END;
$$
LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.test_reset_takeaway_order (p_order_number text) IS 'Reset one takeaway order to ''restaurant_unconfirmed'' with no pickup time; returns a message.';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- select test_reset_takeaway_order('ELAS-AZML-22');

-- select * from takeaway_summary where order_number='ELAS-AZML-22';
