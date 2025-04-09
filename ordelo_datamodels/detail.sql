CREATE TYPE vehicle_enum AS ENUM ('bicycle', 'ebike', 'bike', 'car');

CREATE TABLE delivery_detail (
    order_number     VARCHAR(100),
    vehicle_type     vehicle_enum NOT NULL DEFAULT 'car',
    rider_payout    DOUBLE PRECISION NOT NULL,
    distance         DOUBLE PRECISION NOT NULL,
    rest_id          VARCHAR(50) NOT NULL, -- restaurant id
    rest_name        TEXT NOT NULL,
    rest_lon         DOUBLE PRECISION NOT NULL,
    rest_lat         DOUBLE PRECISION NOT NULL,
    rest_address     TEXT NOT NULL,
    town        VARCHAR(255) NOT NULL,
    customer_id          VARCHAR(50) NOT NULL, -- customer id
    customer_name        TEXT NOT NULL,
    customer_lon         DOUBLE PRECISION NOT NULL,
    customer_lat         DOUBLE PRECISION NOT NULL,
    customer_address     TEXT NOT NULL,
    status          VARCHAR(50) NOT NULL CHECK (status IN ('unassigned', 'declined', 'timedout', 'assigned', 'completed')),
    dispatch_id     INTEGER,
    rider_id        VARCHAR(12),
    dt               DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    PRIMARY KEY (order_number, vehicle_type)
);