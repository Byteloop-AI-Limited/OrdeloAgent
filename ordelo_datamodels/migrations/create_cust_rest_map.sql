-- MIGRATION (history; do not edit the statements below)
-- Applied to live: Applied: every object it creates exists live (checked 2026-10-16).
-- Current definitions now live in: core/cust_rest_map.sql
-- Purpose: Customer-to-restaurant consent table.
-- The feature files above are the current truth; this file only records the one-off change.

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
