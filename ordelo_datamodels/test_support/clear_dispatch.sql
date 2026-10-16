-- =============================================================================================
-- ordelo_datamodels/test_support/clear_dispatch.sql
-- Test helper: delete every dispatch of the most recently dispatched order (so the rider offer can be sent again).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     clear_dispatch() -> void
--                   Delete the dispatches of the latest dispatched order.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call DELETEs delivery_dispatch rows.
-- HOW IT FITS   Developer and operator helpers for live testing. They change real rows, so they are run by hand (or by the WhatsApp
--                 /reset and /test utility commands in watomation/on_message_wa_handler.py), never by the application flow.
--                 See docs/live-order-test-harness.md and test_support/test_restaurant_notices.sql.
-- LIFECYCLE     none
-- CALLED BY     clear_dispatch:
--                 python    watomation/on_message_wa_handler.py: clear_dispatch()
-- PYTHON MODEL  none
-- SECURITY      clear_dispatch(): executable by PUBLIC (default)
-- TESTS         tests/regressions/test_p7_msg_handler.py
-- GOTCHAS       Acts on whichever order was dispatched last, not on a chosen order.
-- SEE ALSO      test_support/test_reset_order_and_dispatch.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function clear_dispatch() -> void
--   Delete the dispatches of the latest dispatched order.
--   Data: writes delivery_dispatch.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION clear_dispatch ()
    RETURNS void
    AS $$
BEGIN
    -- delete dispatch so I can get the msg
    WITH latestRecord AS (
        SELECT
            order_number
        FROM
            delivery_dispatch
        ORDER BY
            dtts DESC
        LIMIT 1)
DELETE FROM delivery_dispatch dispatch
WHERE EXISTS (
        SELECT
            1
        FROM
            latestRecord
        WHERE
            order_number = dispatch.order_number);
END;
$$
LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.clear_dispatch () IS 'Delete the dispatches of the latest dispatched order.';
