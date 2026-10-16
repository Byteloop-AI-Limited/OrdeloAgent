CREATE TABLE IF NOT EXISTS public.delivery_pricing_detail (
    order_number character varying(100) NOT NULL,
    distance double precision NOT NULL,
    message text,
    minimum_order_value numeric(10,2) DEFAULT NULL::numeric,
    CONSTRAINT delivery_pricing_detail_pkey PRIMARY KEY (order_number)
);

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
