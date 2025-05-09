-- 1. Create custom enum types
-- DROP TYPE vehicle_type_enum cascade;
CREATE TYPE vehicle_type_enum AS ENUM ('bicycle', 'electric_bike', 'scooter', 'car');

-- 2. Driver Master Table

CREATE TABLE rider_master (
    id          SERIAL PRIMARY KEY,
    rider_id   VARCHAR(12) ,
    rider_name     TEXT NOT NULL,
    vehicle_type vehicle_type_enum NOT NULL,
    town        VARCHAR(255) NOT NULL,
    status      VARCHAR(50) NOT NULL,
    is_in_shift BOOLEAN NOT NULL DEFAULT TRUE,
    dtts        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE restaurant_master (
    rest_ref    VARCHAR(4) PRIMARY KEY,
    rest_id   VARCHAR(12) UNIQUE,
    rest_name     TEXT NOT NULL,
    rest_email     TEXT NULL,
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


-- Test Values 
INSERT INTO restaurant_master (
    rest_ref,
    rest_id,
    rest_name,
    rest_email,
    house_number,
    building_name,
    street_name,
    city,
    postcode,
    lat,
    lon
) VALUES (
    'ELAB',                              
    '447440880754',                     
    'Elai - Basingstoke',               
    NULL,                               
    'Unit 1',                           
    'Anchor Court',                     
    'London Street',                    
    'Basingstoke',                      
    'RG21 7NY',                        
    51.26266799796382,                 
    -1.084616059190678                
);

INSERT INTO restaurant_master (
    rest_ref,
    rest_id,
    rest_name,
    rest_email,
    house_number,
    building_name,
    street_name,
    city,
    postcode,
    lat,
    lon
) VALUES (
    'WREN',
    '447448440754',
    'Warren Road School',
    NULL,
    '1',
    NULL,
    'Warren Road',
    'Orpington',
    'BR6 6JF',
    51.36024994020377,
    0.09075077116472913
);

-- INSERT sample data into rider_master
INSERT INTO rider_master (
    rider_id, rider_name, vehicle_type, town, status, dtts
) VALUES
    ('447448440754', 'Lohith', 'car', 'Basingstoke', 'active', CURRENT_TIMESTAMP),
    ('447446933210', 'Rahul', 'bike', 'Basingstoke', 'active', CURRENT_TIMESTAMP),
    ('447424334783', 'Chaitra', 'bike', 'Basingstoke', 'active', CURRENT_TIMESTAMP);