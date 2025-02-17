CREATE TABLE delivery_pricing_detail (
    order_number     VARCHAR(100) NOT NULL,
    distance         DOUBLE PRECISION NOT NULL,
    byteloop_cost    DOUBLE PRECISION NOT NULL,
    rest_cost    DOUBLE PRECISION NOT NULL,
    driver_payout    DOUBLE PRECISION NOT NULL,
    dt               DATE NOT NULL DEFAULT CURRENT_DATE,
    ddts             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
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