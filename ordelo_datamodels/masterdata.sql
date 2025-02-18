-- 1. Create custom enum types

-- CREATE TYPE vehicle_type_enum AS ENUM ('bike', 'electric_bike', 'car', 'cycle');

-- 2. Driver Master Table
CREATE TABLE driver_master (
    driver_id   VARCHAR(12) PRIMARY KEY,
    vehicle_type vehicle_type_enum NOT NULL,
    town        VARCHAR(255) NOT NULL,
    status      VARCHAR(50) NOT NULL,
    dtts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) WITH (OIDS=FALSE);

CREATE TABLE restaurant_master (
    rest_id   VARCHAR(12) PRIMARY KEY,
    rest_name     TEXT NOT NULL,
    rest_town        VARCHAR(255) NOT NULL,
    rest_location POINT NOT NULL,
    rest_address     TEXT NOT NULL,
    dt          DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) WITH (OIDS=FALSE);

CREATE TABLE customer_master (
    cust_id   VARCHAR(12) PRIMARY KEY,
    cust_name     TEXT NOT NULL,
    cust_town        VARCHAR(255) NOT NULL,
    cust_location POINT NOT NULL,
    cust_address     TEXT NOT NULL,
    dt          DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) WITH (OIDS=FALSE);
