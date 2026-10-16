CREATE TABLE IF NOT EXISTS public.order_item_v2 (
    order_id text,
    product_name text NOT NULL,
    sku text NOT NULL,
    quantity integer NOT NULL,
    price double precision NOT NULL,
    modifications text[],
    CONSTRAINT order_item_v2_order_id_fkey FOREIGN KEY (order_id) REFERENCES food_order(order_id) ON DELETE CASCADE
);
