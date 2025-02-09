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
CREATE TABLE reservation (
    reservation_id TEXT PRIMARY KEY,
    seq_id INTEGER,
    recipient TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    reservation_dt DATE DEFAULT CURRENT_DATE, 
    reservation_ts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    confirmation_status TEXT NOT NULL,
    CONSTRAINT confirmation_status_enum CHECK (confirmation_status IN ('confirmed', 'not_confirmed'))
);

-- %% cascaded drop
DROP TABLE IF EXISTS reservation;