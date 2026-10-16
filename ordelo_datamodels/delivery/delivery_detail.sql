
CREATE TABLE delivery_detail (
    order_number     VARCHAR(100),
    customer_id      VARCHAR(12) NOT NULL,
    vehicle_type    VARCHAR(15) NOT NULL,
    town        VARCHAR(255) NOT NULL,
    rider_payout    DOUBLE PRECISION NOT NULL,
    distance         DOUBLE PRECISION NOT NULL,
    status          VARCHAR(50) NOT NULL CHECK (status IN ('unassigned', 'assigned', 'vehicle_type_timedout', 'completed')),
    dispatch_id     INTEGER,
    rider_id        VARCHAR(12),
    dt               DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts             TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (order_number, vehicle_type)
);
