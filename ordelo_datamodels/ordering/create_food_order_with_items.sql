-- ---------------------------------------------------------------------------
-- R1a  F4: create the order and its items in one transaction
-- ---------------------------------------------------------------------------
-- p_order: {order_id, order_number, seq_id, recipient, notes, thread_id, action,
--           total_price, payment_status?, origin_channel?, storefront?}
-- p_items: [{product_name, sku, quantity, price, modifications?}, …]
-- Payment environment is derived from these items, never caller-selected.
-- Any failure (including a duplicate order_id) raises and rolls back both inserts.
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
