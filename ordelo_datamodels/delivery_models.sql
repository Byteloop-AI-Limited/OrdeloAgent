CREATE TABLE delivery_pricing_detail (
    order_number     VARCHAR(100) NOT NULL,
    distance         DOUBLE PRECISION NOT NULL,
    byteloop_cost    DOUBLE PRECISION NOT NULL,
    rest_cost    DOUBLE PRECISION NOT NULL,
    driver_payout    DOUBLE PRECISION NOT NULL,
    dt               DATE NOT NULL DEFAULT CURRENT_DATE,
    ddts             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
);


CREATE TABLE delivery_dispatch (
    dispatch_id      SERIAL PRIMARY KEY,
    order_number     VARCHAR(100) NOT NULL,
    rider_id        VARCHAR(12) NOT NULL,
    rider_payout    DOUBLE PRECISION NOT NULL,
    distance         DOUBLE PRECISION NOT NULL,
    status  VARCHAR(50) NOT NULL,
    dt               DATE NOT NULL DEFAULT CURRENT_DATE,
    ddts             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE delivery_inflight (
    dispatch_id      VARCHAR(100) NOT NULL,
    order_number     VARCHAR(100) NOT NULL,
    rider_id        VARCHAR(12) NOT NULL,
    customer_id        VARCHAR(12) NOT NULL,
    dt               DATE NOT NULL DEFAULT CURRENT_DATE,
    ddts             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (dispatch_id)
);


-- Create a table for the location events
CREATE TABLE delivery_inflight_location_events (
    dispatch_id    VARCHAR(100) NOT NULL,
    order_number   VARCHAR(100) NOT NULL,
    driver_id      VARCHAR(12) NOT NULL,
    cust_id        VARCHAR(12) NOT NULL,
    event_type     VARCHAR(50) NOT NULL, -- 'res_enter', 'res_leave',  'cust_enter', 'cust_leave'
    res_enter_dtts TIMESTAMP,
    res_leave_dtts TIMESTAMP,
    cust_enter_dtts TIMESTAMP,
    cust_leave_dtts TIMESTAMP,
    dt             DATE NOT NULL,
    ddts           TIMESTAMP NOT NULL
);

-- Create a trigger function to handle the insertion and deletion logic
CREATE OR REPLACE FUNCTION handle_delivery_dispatch_changes()
RETURNS TRIGGER AS $$
BEGIN
    -- Insert into delivery_inflight when status is 'open'
    IF TG_OP = 'UPDATE' AND NEW.status = 'open' THEN
        INSERT INTO delivery_inflight (dispatch_id, order_number, rider_id, customer_id, dt, ddts)
        VALUES (NEW.dispatch_id, NEW.order_number, NEW.rider_id, NEW.customer_id, NEW.dt, NEW.ddts);
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' AND NEW.status = 'closed' THEN
        DELETE FROM delivery_inflight WHERE dispatch_id = OLD.dispatch_id;
        RETURN NEW;
    END IF;
    RETURN NULL; -- For other operations, do nothing
END;
$$ LANGUAGE plpgsql;

-- Create a trigger for insert operation
CREATE TRIGGER insert_delivery_inflight
AFTER INSERT ON delivery_dispatch
FOR EACH ROW
EXECUTE FUNCTION handle_delivery_dispatch_changes();

-- Create a trigger for update operation
CREATE TRIGGER update_delivery_inflight
AFTER UPDATE ON delivery_dispatch
FOR EACH ROW
EXECUTE FUNCTION handle_delivery_dispatch_changes();
-- Drop the trigger
DROP TRIGGER update_delivery_inflight ON delivery_dispatch;



-- For rest insert 
ALTER TABLE delivery_dispatch ENABLE ROW LEVEL SECURITY;
CREATE POLICY insert_policy ON delivery_dispatch
FOR INSERT
WITH CHECK (auth.uid() IS NOT NULL);

-- For all tables in public
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN SELECT table_name 
              FROM information_schema.tables 
              WHERE table_schema = 'public' 
                AND table_type = 'BASE TABLE'
                AND table_name != 'spatial_ref_sys'  -- Exclude system tables
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', r.table_name);
    END LOOP;
END $$;

-- Show table schema
SELECT 
    table_name, 
    column_name, 
    data_type, 
    is_nullable 
FROM 
    information_schema.columns 
WHERE 
    table_name = 'delivery_detail';