-- =============================================================================================
-- ordelo_datamodels/test_support/test_reset_order_and_dispatch.sql
-- Test helper: reset a delivery order to 'restaurant_unconfirmed' so the restaurant and dispatch flow can be replayed.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     test_reset_order_and_dispatch(p_order_number text) -> text
--                   Delete the order's dispatch-side rows and put the summary back to 'restaurant_unconfirmed'; returns the counts.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call deletes the order's inflight, dispatch and detail rows and resets its delivery_summary
--               (status and restaurant_confirmation_status 'restaurant_unconfirmed', pickup_time NULL, dtts now): the restaurant trigger fires.
-- HOW IT FITS   Developer and operator helpers for live testing. They change real rows, so they are run by hand (or by the WhatsApp
--                 /reset and /test utility commands in watomation/on_message_wa_handler.py), never by the application flow.
--                 See docs/live-order-test-harness.md and test_support/test_restaurant_notices.sql.
-- LIFECYCLE     none
-- CALLED BY     test_reset_order_and_dispatch:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      test_reset_order_and_dispatch(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       none
-- SEE ALSO      test_support/cleanup_delivery_order.sql
--               test_support/test_reset_takeaway_order.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function test_reset_order_and_dispatch(p_order_number text) -> text
--   Delete the order's dispatch-side rows and put the summary back to 'restaurant_unconfirmed'; returns the counts.
--   Data: writes delivery_detail, delivery_dispatch, delivery_inflight, delivery_summary.
-- ---------------------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS test_reset_order_and_dispatch (text);

CREATE OR REPLACE FUNCTION test_reset_order_and_dispatch (p_order_number text)
    RETURNS text
    AS $$
DECLARE
    v_inflight_deleted integer;
    v_dispatch_deleted integer;
    v_detail_deleted integer;
    v_summary_updated integer;
BEGIN
    -- Delete inflight rows for the order
    DELETE FROM delivery_inflight
    WHERE order_number = p_order_number;
    GET DIAGNOSTICS v_inflight_deleted = ROW_COUNT;
    -- Delete dispatch rows for the order
    DELETE FROM delivery_dispatch
    WHERE order_number = p_order_number;
    GET DIAGNOSTICS v_dispatch_deleted = ROW_COUNT;
    -- Delete delivery detail rows for the order
    DELETE FROM delivery_detail
    WHERE order_number = p_order_number;
    GET DIAGNOSTICS v_detail_deleted = ROW_COUNT;
    -- Reset summary status to unassigned; Bypass rest confirmation
    UPDATE
        delivery_summary
    SET
        status = 'restaurant_unconfirmed',
        restaurant_confirmation_status = 'restaurant_unconfirmed',
        pickup_time = NULL,
        dtts = CURRENT_TIMESTAMP
    WHERE
        order_number = p_order_number;
    GET DIAGNOSTICS v_summary_updated = ROW_COUNT;
    -- Reset summary status to unassigned; Bypass rest confirmation
    -- UPDATE delivery_summary
    -- SET
    -- status = 'unassigned',
    -- restaurant_confirmation_status = 'auto_accept',
    -- pickup_time = current_timestamp + interval '10 minutes',
    -- dtts = current_timestamp
    -- WHERE order_number = p_order_number;
    -- GET DIAGNOSTICS v_summary_updated = ROW_COUNT;
    RETURN format('Order %s reset (inflight deleted=%s, dispatch deleted=%s, detail deleted=%s, summary updated=%s)', p_order_number, v_inflight_deleted, v_dispatch_deleted, v_detail_deleted, v_summary_updated);
END;
$$
LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.test_reset_order_and_dispatch(p_order_number text) IS 'Delete the order''s dispatch-side rows and put the summary back to ''restaurant_unconfirmed''; returns the counts.';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- select test_reset_order_and_dispatch('ELAS-ZVEO-29');

----------------------------------------
-- TimeoutUnassignedDispatch
----------------------------------------
-- UPDATE delivery_dispatch
-- SET status = 'timedout'
-- WHERE status = 'unassigned'
-- AND (current_timestamp - dtts) > interval '30 seconds';
