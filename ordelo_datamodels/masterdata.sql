-- 1. Create custom enum types

-- CREATE TYPE vehicle_type_enum AS ENUM ('bike', 'electric_bike', 'car', 'cycle');

-- 2. Driver Master Table

CREATE TABLE rider_master (
    id          SERIAL PRIMARY KEY,
    rider_id   VARCHAR(12) UNIQUE,
    rider_name     TEXT NOT NULL,
    vehicle_type vehicle_type_enum NOT NULL,
    town        VARCHAR(255) NOT NULL,
    status      VARCHAR(50) NOT NULL,
    dtts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE restaurant_master (
    id          VARCHAR(3) PRIMARY KEY,
    rest_id   VARCHAR(12) UNIQUE,
    rest_name     TEXT NOT NULL,
    rest_email     TEXT NULL,
    house_number     TEXT NOT NULL,
    building_name     TEXT NOT NULL,
    street_name     TEXT NOT NULL,
    city     TEXT NOT NULL,
    postcode     TEXT NOT NULL,
    lat        FLOAT NOT NULL,
    lon        FLOAT NOT NULL,
    dt          DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE TABLE customer_master (
    cust_id   VARCHAR(12) PRIMARY KEY,
    cust_name     TEXT NOT NULL,
    cust_email     TEXT NULL,
    house_number     TEXT NOT NULL,
    building_name     TEXT NOT NULL,
    street_name     TEXT NOT NULL,
    city     TEXT NOT NULL,
    postcode     TEXT NOT NULL,
    lat        FLOAT NOT NULL,
    lon        FLOAT NOT NULL,
    dt          DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- INSERT sample data into rider_master
INSERT INTO rider_master (rider_id, rider_name, vehicle_type, town, status, dtts)
VALUES
    ('447448440754', 'Lohith', 'car', 'Basingstoke', 'active', CURRENT_TIMESTAMP),
    ('447446933210', 'Rahul', 'bike', 'Basingstoke', 'active', CURRENT_TIMESTAMP),
    ('447424334783', 'Chaitra', 'bike', 'Basingstoke', 'active', CURRENT_TIMESTAMP)