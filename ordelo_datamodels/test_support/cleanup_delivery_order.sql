-- =============================================================================================
-- ordelo_datamodels/test_support/cleanup_delivery_order.sql
-- Test helper: delete a delivery order's dispatch, detail, inflight and summary rows.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     cleanup_delivery_order(p_order_number text) -> text
--                   Remove every delivery-workflow row of an order; returns a message with the counts.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call DELETEs the order's rows from delivery_inflight, delivery_dispatch, delivery_detail and delivery_summary.
-- HOW IT FITS   Developer and operator helpers for live testing. They change real rows, so they are run by hand (or by the WhatsApp
--                 /reset and /test utility commands in watomation/on_message_wa_handler.py), never by the application flow.
--                 See docs/live-order-test-harness.md and test_support/test_restaurant_notices.sql.
-- LIFECYCLE     none
-- CALLED BY     cleanup_delivery_order:
--                 python    watomation/on_message_wa_handler.py: test_delivery()
-- PYTHON MODEL  none
-- SECURITY      cleanup_delivery_order(): executable by PUBLIC (default)
-- TESTS         tests/watomation/test_on_message_wa_handler.py
-- GOTCHAS       none
-- SEE ALSO      test_support/test_reset_order_and_dispatch.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function cleanup_delivery_order(p_order_number text) -> text
--   Remove every delivery-workflow row of an order; returns a message with the counts.
--   Data: writes delivery_detail, delivery_dispatch, delivery_inflight, delivery_summary.
-- ---------------------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS cleanup_delivery_order (text);

CREATE OR REPLACE FUNCTION cleanup_delivery_order (p_order_number text)
    RETURNS text
    AS $$
DECLARE
    v_dispatch_count integer;
    v_detail_count integer;
    v_summary_count integer;
    v_inflight_count integer;
    v_total_count integer;
BEGIN
    -- Check if order exists
    IF NOT EXISTS (
        SELECT
            1
        FROM
            delivery_summary
        WHERE
            order_number = p_order_number) THEN
    RETURN 'Order ' || p_order_number || ' not found';
END IF;
    -- Delete from delivery_inflight (must be first due to foreign key constraints)
    DELETE FROM delivery_inflight
    WHERE dispatch_id IN (
            SELECT
                dispatch_id
            FROM
                delivery_detail
            WHERE
                order_number = p_order_number);
    GET DIAGNOSTICS v_inflight_count = ROW_COUNT;
    -- Delete from delivery_dispatch
    DELETE FROM delivery_dispatch
    WHERE order_number = p_order_number;
    -- Delete from delivery_detail
    DELETE FROM delivery_detail
    WHERE order_number = p_order_number;
    GET DIAGNOSTICS v_dispatch_count = ROW_COUNT;
    -- Delete from delivery_detail
    DELETE FROM delivery_detail
    WHERE order_number = p_order_number;
    GET DIAGNOSTICS v_detail_count = ROW_COUNT;
    -- Delete from delivery_summary
    DELETE FROM delivery_summary
    WHERE order_number = p_order_number;
    GET DIAGNOSTICS v_summary_count = ROW_COUNT;
    -- Calculate total deletions
    v_total_count := v_inflight_count + v_dispatch_count + v_detail_count + v_summary_count;

    RETURN 'Order ' || p_order_number || ' cleaned up. Deleted: ' || v_summary_count || ' summary, ' || v_detail_count || ' detail, ' || v_dispatch_count || ' dispatch, ' || v_inflight_count || ' inflight records. Total: ' || v_total_count;
END;
$$
LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.cleanup_delivery_order (p_order_number text) IS 'Remove every delivery-workflow row of an order; returns a message with the counts.';
