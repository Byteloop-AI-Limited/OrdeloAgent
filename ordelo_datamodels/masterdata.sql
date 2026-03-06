-- 1. Create custom enum types
-- DROP TYPE vehicle_type_enum cascade;

-- 2. Driver Master Table

CREATE TABLE rider_master (
    id          SERIAL PRIMARY KEY,
    rider_id   VARCHAR(12) ,
    rider_name     TEXT NOT NULL,
    vehicle_type VARCHAR(15) NOT NULL,
    town        VARCHAR(255) NOT NULL,
    status      VARCHAR(50) NOT NULL,
    is_in_shift BOOLEAN NOT NULL DEFAULT TRUE,
    priority    INT NOT NULL DEFAULT 1,
    dtts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE rider_master ADD COLUMN shift_response_dtts TIMESTAMP;


CREATE TABLE restaurant_master (
    rest_ref    VARCHAR(4) PRIMARY KEY,
    rest_id   VARCHAR(12) UNIQUE,
    rest_name     TEXT NOT NULL,
    rest_email     TEXT NULL,
    admins TEXT[] NULL,
    house_number     TEXT NOT NULL,
    building_name     TEXT NULL,
    street_name     TEXT NOT NULL,
    city     TEXT NOT NULL,
    postcode     TEXT NOT NULL,
    lat        FLOAT NOT NULL,
    lon        FLOAT NOT NULL,
    dt          DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

ALTER TABLE restaurant_master
  ADD COLUMN rest_stale_active_threads_minutes INT NOT NULL DEFAULT 10,
  ADD COLUMN restaurant_start_time FLOAT NOT NULL DEFAULT 12,
  ADD COLUMN restaurant_end_time FLOAT NOT NULL DEFAULT 21.30;

ALTER TABLE restaurant_master
  ALTER COLUMN rest_stale_active_threads_minutes
  TYPE INT
  USING rest_stale_active_threads_minutes::INT;

CREATE TABLE customer_master (
    cust_id   VARCHAR(12) PRIMARY KEY,
    cust_name     TEXT NOT NULL,
    cust_email     TEXT NULL,
    house_number     TEXT NOT NULL,
    building_name     TEXT NULL,
    street_name     TEXT NOT NULL,
    city     TEXT NOT NULL,
    postcode     TEXT NOT NULL,
    lat        FLOAT NOT NULL,
    lon        FLOAT NOT NULL,
    dt          DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

ALTER TABLE customer_master
  ADD COLUMN consented_rest_refs TEXT[] NOT NULL DEFAULT '{}';

-- Test Values
