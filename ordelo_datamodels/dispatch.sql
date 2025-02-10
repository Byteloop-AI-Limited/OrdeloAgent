CREATE TABLE delivery_dispatch (
    dispatch_id      VARCHAR(100) NOT NULL,
    order_number     VARCHAR(100) NOT NULL,
    driver_id        VARCHAR(12) NOT NULL,
    driver_payout    DOUBLE PRECISION NOT NULL,
    distance         DOUBLE PRECISION NOT NULL,
    recipient        VARCHAR(12) NOT NULL,
    rest_id          VARCHAR(50) NOT NULL, -- restaurant id
    rest_location    POINT NOT NULL,   -- represents (lat, lon)
    rest_address     TEXT NOT NULL,
    cust_id          VARCHAR(50) NOT NULL, -- customer id
    cust_location    POINT NOT NULL,   -- represents (lat, lon)
    cust_address     TEXT NOT NULL,
    dt               DATE NOT NULL,
    ddts             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status  VARCHAR(50) NOT NULL
) WITH (OIDS=FALSE);


CREATE TABLE delivery_inflight (
    dispatch_id      VARCHAR(100) NOT NULL,
    order_number     VARCHAR(100) NOT NULL,
    driver_id        VARCHAR(12) NOT NULL,
    cust_id        VARCHAR(12) NOT NULL,
    dt               DATE NOT NULL,
    ddts             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (dispatch_id)
) WITH (OIDS=FALSE);


-- Create a trigger function to handle the insertion and deletion logic
CREATE OR REPLACE FUNCTION handle_delivery_dispatch_changes()
RETURNS TRIGGER AS $$
BEGIN
    -- Insert into delivery_inflight when status is 'open'
    IF TG_OP = 'INSERT' AND NEW.status = 'open' THEN
        INSERT INTO delivery_inflight (dispatch_id, order_number, driver_id, cust_id, dt, ddts)
        VALUES (NEW.dispatch_id, NEW.order_number, NEW.driver_id, NEW.cust_id, NEW.dt, NEW.ddts);
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


-- Create a table for the location events
CREATE TABLE delivery_inflight_location_events (
    dispatch_id    VARCHAR(100) NOT NULL,
    order_number   VARCHAR(100) NOT NULL,
    driver_id      VARCHAR(12) NOT NULL,
    cust_id        VARCHAR(12) NOT NULL,
    event_type     VARCHAR(50) NOT NULL, -- 'res_enter', 'res_leave',  'cust_enter', 'cust_leave'
    dt             DATE NOT NULL,
    ddts           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);