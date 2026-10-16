-- =============================================================================================
-- ordelo_datamodels/ordering/create_food_order_with_items.sql
-- Create an order (food_order) and its lines (order_item) atomically, choosing the payment environment from the items.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     create_food_order_with_items(p_order jsonb, p_items jsonb) -> jsonb
--                   Insert one food_order row and its order_item rows in one transaction and return {order, item_count}.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call inserts one food_order row and one order_item row per item (when the file is applied: none).
-- HOW IT FITS   Order creation, both channels:
--                 WhatsApp: restaurant-agents builds the basket -> utils_common/order_management/order_service.py
--                 Web:      utils_common/web_ordering/web_checkout.py (restaurant-frontend checkout)
--                   -> get_next_daily_seq() (restaurant-agents) for the order number
--                   -> create_food_order_with_items(): food_order + order_item in one transaction
--                   -> payment link; the payment callback records the authorisation (record_payment_authorised)
--                   -> /payment-hooks/payment-complete -> init_delivery() or init_takeaway() starts fulfilment.
--                 food_order and order_item are defined by restaurant-agents; OrdeloAgent adds columns to food_order in
--                 ordering/food_order_additions.sql (origin_channel, storefront, payment_mode, idempotency_key).
-- LIFECYCLE     food_order.payment_status starts at the caller's value (default 'requires_payment'); payment moves it on.
-- CALLED BY     create_food_order_with_items:
--                 python    utils_common/order_management/order_service.py: _insert_order_rpc()
--                 python    utils_common/web_ordering/web_checkout.py: create()
-- PYTHON MODEL  none
-- SECURITY      create_food_order_with_items(): executable by PUBLIC (default)
-- TESTS         tests/utils_common/order_management/test_order_service.py
-- GOTCHAS       payment_mode is never chosen by the caller: any item named 'TEST3100' makes the order 'test' (Stripe test keys),
--                 otherwise 'live'. See plans/test3100-payment-routing-plan.md.
--               Four frozen copies of this function live in migrations/ (ordelo_agg_r1, r1_test_payment, r3, test3100); they are history.
--                 This file is the current definition.
-- SEE ALSO      ordering/food_order_additions.sql
--               ordering/order_has_test_item.sql
--               docs/test-orders.md
--               docs/web-ordering-playground.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function create_food_order_with_items(p_order jsonb, p_items jsonb) -> jsonb
--   Insert one food_order row and its order_item rows in one transaction and return {order, item_count}.
--   p_order: {order_id, order_number, seq_id, recipient, notes, thread_id, action, total_price, payment_status?,
--             origin_channel?, storefront?, idempotency_key?}
--   p_items: [{product_name, sku, quantity, price, modifications?}, ...] (must be a non-empty array, else RAISE).
--   Any failure, including a duplicate order_id, raises and rolls back both inserts.
--   Data: writes food_order, order_item.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.create_food_order_with_items (p_order jsonb, p_items jsonb)
    RETURNS jsonb
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_order jsonb;
    v_items integer;
BEGIN
    IF p_items IS NULL OR jsonb_typeof(p_items) <> 'array' OR jsonb_array_length(p_items) = 0 THEN
        RAISE EXCEPTION 'create_food_order_with_items: p_items must be a non-empty array';
    END IF;

    INSERT INTO public.food_order (order_id, order_number, seq_id, recipient, notes, thread_id, action, total_price, payment_status, origin_channel, storefront, payment_mode, idempotency_key)
        VALUES (p_order ->> 'order_id', p_order ->> 'order_number', (p_order ->> 'seq_id')::integer, p_order ->> 'recipient', p_order ->> 'notes', p_order ->> 'thread_id', p_order ->> 'action', (p_order ->> 'total_price')::double precision, COALESCE(p_order ->> 'payment_status', 'requires_payment'), COALESCE(p_order ->> 'origin_channel', 'whatsapp'), COALESCE(p_order ->> 'storefront', 'direct'), CASE WHEN EXISTS (
                SELECT
                    1
                FROM
                    jsonb_array_elements(p_items) x
                WHERE
                    x ->> 'product_name' = 'TEST3100') THEN
                'test'
            ELSE
                'live'
            END,
            NULLIF (p_order ->> 'idempotency_key', ''))
RETURNING
    to_jsonb (food_order.*) INTO v_order;

    INSERT INTO public.order_item (order_id, product_name, sku, quantity, price, modifications)
    SELECT
        p_order ->> 'order_id',
        x ->> 'product_name',
        x ->> 'sku',
        (x ->> 'quantity')::integer,
        (x ->> 'price')::double precision,
        CASE WHEN jsonb_typeof(x -> 'modifications') = 'array' THEN
            ARRAY (
                SELECT
                    jsonb_array_elements_text(x -> 'modifications'))
        ELSE
            NULL
        END
    FROM
        jsonb_array_elements(p_items) AS x;
    GET DIAGNOSTICS v_items = ROW_COUNT;

    RETURN jsonb_build_object('order', v_order, 'item_count', v_items);
END
$$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.create_food_order_with_items (p_order jsonb, p_items jsonb) IS 'Insert one food_order row and its order_item rows in one transaction and return {order, item_count}.';
