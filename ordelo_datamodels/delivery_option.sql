CREATE TABLE delivery_option (
    id                      SERIAL PRIMARY KEY,
    vehicle_type            VARCHAR(20) NOT NULL,
    minimum_order_value     DOUBLE PRECISION NOT NULL,
    byteloop_commission_fee DOUBLE PRECISION,
    byteloop_commission_percentage DOUBLE PRECISION,
    rest_cost               DOUBLE PRECISION,
    driver_payout           DOUBLE PRECISION,
    breakdown               JSONB,
    rank                    INTEGER,
    final_order_value       DOUBLE PRECISION,
    total_customer_charge   DOUBLE PRECISION,
    order_number            VARCHAR(100),
    message                 TEXT,
    dt                      DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts                    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- change driver_payout to rider_payout