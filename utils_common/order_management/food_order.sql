CREATE SEQUENCE daily_seq START WITH 20;
-- drop sequence daily_seq;
-- Table to store the last date when the sequence was used
CREATE TABLE IF NOT EXISTS daily_seq_last_value (
    last_value_date DATE PRIMARY KEY
);

-- drop function get_next_daily_seq;
-- Function to get the next value from the sequence based on the current date
CREATE OR REPLACE FUNCTION get_next_daily_seq(input_date DATE)
RETURNS INTEGER AS $$DECLARE
    seq_value INTEGER;
    date_exists BOOLEAN;
BEGIN
    -- Check if the input_date already exists in the table
    SELECT EXISTS(SELECT 1 FROM daily_seq_last_value WHERE last_value_date = input_date) INTO date_exists;

    -- If the input date does not exist, reset the sequence and insert the new date
    IF NOT date_exists THEN
        PERFORM setval('daily_seq', 20, false);
        INSERT INTO daily_seq_last_value (last_value_date) VALUES (input_date);
    END IF;

    -- Get the next value from the sequence
    seq_value := nextval('daily_seq');
    RETURN seq_value;
END;$$ LANGUAGE plpgsql;

-- DROP TABLE public.food_order CASCADE;
CREATE TABLE public.food_order (
    order_number TEXT PRIMARY KEY,
    order_id TEXT UNIQUE,
    seq_id INTEGER,
    recipient TEXT NOT NULL,
    notes TEXT NULL,
    thread_id TEXT NOT NULL,
    action TEXT NOT NULL,
    total_price FLOAT NOT NULL,
    final_order_value FLOAT NULL,
    rest_cost FLOAT NULL,
    service_charge FLOAT NULL,
    delivery_fee FLOAT NULL,
    small_order_fee FLOAT NULL,
    commission_rate FLOAT NULL,
    payment_status TEXT NOT NULL,
    order_dt DATE DEFAULT CURRENT_DATE, 
    order_dtts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);


-- Create the OrderItem table
CREATE TABLE public.order_item (
    order_id TEXT,
    product_name TEXT NOT NULL,
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price FLOAT NOT NULL,
    modifications TEXT[] NULL,
    FOREIGN KEY (order_id) REFERENCES public.food_order(order_id) ON DELETE CASCADE
);

ALTER TABLE public.order_item
    ADD COLUMN IF NOT EXISTS modifications TEXT[] NULL;

-- Create the OrderItem table
CREATE TABLE public.order_item_v2 (
    order_id TEXT,
    product_name TEXT NOT NULL,
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price FLOAT NOT NULL,
    modifications TEXT[] NULL,
    FOREIGN KEY (order_id) REFERENCES public.food_order(order_id) ON DELETE CASCADE
);


-- %% cascaded drop
DROP TABLE IF EXISTS OrderItem;
DROP TABLE IF EXISTS FoodOrder;

select * from food_order where order_number like 'SFCS-ESUY-24';
select * from order_item_v2 where order_id = 'ESUY-24';
select * from order_item where order_id = 'HXKS-29';

-- delete from order_item where order_id = 'ESUY-24';