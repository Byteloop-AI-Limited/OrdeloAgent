-- Exact, order-scoped marker lookup. NULL means the order does not exist.
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
