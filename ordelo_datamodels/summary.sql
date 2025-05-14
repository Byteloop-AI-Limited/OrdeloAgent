
CREATE TABLE delivery_summary (
    order_number     VARCHAR(100),
    rest_id          VARCHAR(12) NOT NULL, -- restaurant id
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
    status          VARCHAR(50) NOT NULL CHECK (status IN ('unassigned', 'timedout', 'assigned', 'completed')),
    rest_confirmation_code INTEGER NOT NULL,
    cust_confirmation_code INTEGER NOT NULL,
    pickup_time      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP + INTERVAL '30 minutes',
    pickup_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    dt               DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (order_number)
);
