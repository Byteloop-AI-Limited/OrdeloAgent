-- Migration: create cust_rest_map table
-- Tracks per-customer, per-restaurant consent state

CREATE TABLE cust_rest_map (
    cust_id      VARCHAR(12)              NOT NULL REFERENCES customer_master(cust_id),
    rest_ref     VARCHAR(4)               NOT NULL REFERENCES restaurant_master(rest_ref),
    has_consent  BOOLEAN                  NOT NULL DEFAULT FALSE,
    consent_dtts TIMESTAMP WITH TIME ZONE NULL,
    dtts         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    PRIMARY KEY (cust_id, rest_ref)
);
