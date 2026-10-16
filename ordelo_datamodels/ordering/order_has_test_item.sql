-- =============================================================================================
-- ordelo_datamodels/ordering/order_has_test_item.sql
-- Is this order a TEST3100 test order? (true / false, NULL when the order does not exist)
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     order_has_test_item(p_order_number text) -> boolean
--                   Return whether the order has a 'TEST3100' line; NULL means the order does not exist.
-- REQUIRES      restaurant-agents: food_order
--               restaurant-agents: order_item
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   TEST3100 is the marker product for end-to-end tests. get_available_riders() only offers a TEST3100 order to
--                 riders in ordelo_config overwatch_list, and utils_common/order_management/test_order_dispatch.py uses it to keep
--                 test orders away from real riders. create_food_order_with_items() uses the same marker for payment_mode.
-- LIFECYCLE     none
-- CALLED BY     order_has_test_item:
--                 sql       get_available_riders() (dispatch/job_create_dispatch.sql)
--                 python    utils_common/order_management/test_order_dispatch.py: order_has_test_item()
-- PYTHON MODEL  none
-- SECURITY      order_has_test_item(): executable by PUBLIC (default)
-- TESTS         tests/utils_common/order_management/test_test_order_dispatch.py
--               tests/watomation/routers/test_delivery_hooks.py
-- GOTCHAS       Exact match on order_item.product_name = 'TEST3100'; a renamed product is no longer a test order.
-- SEE ALSO      dispatch/job_create_dispatch.sql (get_available_riders)
--               plans/test3100-payment-routing-plan.md
--               docs/test-orders.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function order_has_test_item(p_order_number text) -> boolean
--   Return whether the order has a 'TEST3100' line; NULL means the order does not exist.
--   Data: reads food_order, order_item.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.order_has_test_item (p_order_number text)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        EXISTS (
            SELECT
                1
            FROM
                order_item oi
            WHERE
                oi.order_id = fo.order_id
                AND oi.product_name = 'TEST3100')
    FROM
        food_order fo
    WHERE
        fo.order_number = p_order_number;
$$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.order_has_test_item (p_order_number text) IS 'Return whether the order has a ''TEST3100'' line; NULL means the order does not exist.';
