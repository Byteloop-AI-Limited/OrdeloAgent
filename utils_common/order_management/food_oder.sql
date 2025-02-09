CREATE SEQUENCE daily_seq START WITH 20;

-- Table to store the last date when the sequence was used
CREATE TABLE IF NOT EXISTS daily_seq_last_value (
    last_value_date DATE PRIMARY KEY
);

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
        ALTER SEQUENCE daily_seq RESTART WITH 20;
        INSERT INTO daily_seq_last_value (last_value_date) VALUES (input_date);
    END IF;

    -- Get the next value from the sequence
    seq_value := nextval('daily_seq');
    RETURN seq_value;
END;$$ LANGUAGE plpgsql;


-- Create the FoodOrder table
CREATE TABLE FoodOrder (
    order_id TEXT PRIMARY KEY,
    seq_id INTEGER,
    recipient TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    total_amount FLOAT NOT NULL,
    order_dt DATE DEFAULT CURRENT_DATE, 
    order_ts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    order_type TEXT NOT NULL,
    payment_status TEXT NOT NULL,
    CONSTRAINT payment_status_enum CHECK (payment_status IN ('awaiting_payment', 'payment_complete', 'payment_abandoned')),
    CONSTRAINT order_type_enum CHECK (order_type IN ('Paid Collection', 'Unpaid Collection', 'Delivery'))
);

-- Create the OrderItem table
CREATE TABLE OrderItem (
    order_id TEXT NOT NULL,
    product_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price FLOAT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES FoodOrder(order_id)
);

-- %% cascaded drop
DROP TABLE IF EXISTS OrderItem;
DROP TABLE IF EXISTS FoodOrder;