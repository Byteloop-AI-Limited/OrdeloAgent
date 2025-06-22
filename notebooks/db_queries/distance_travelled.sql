WITH latest_locations AS (
    -- Get the latest location timestamp for each order
    SELECT 
        order_number,
        rider_id,
        MAX(dtts) AS latest_time
    FROM 
        rider_location
    GROUP BY 
        order_number, rider_id
),
latest_points AS (
    -- Get the details of the latest location
    SELECT 
        r.order_number,
        r.rider_id,
        r.dtts AS latest_time,
        r.lat AS latest_lat,
        r.lon AS latest_lon
    FROM 
        rider_location r
    JOIN 
        latest_locations l ON r.order_number = l.order_number 
                           AND r.rider_id = l.rider_id 
                           AND r.dtts = l.latest_time
),
oldest_in_window AS (
    -- Get the oldest location within 3 minutes of the latest location
    SELECT 
        l.order_number,
        l.rider_id,
        MIN(r.dtts) AS oldest_time
    FROM 
        latest_points l
    JOIN 
        rider_location r ON l.order_number = r.order_number AND l.rider_id = r.rider_id
    WHERE 
        r.dtts >= l.latest_time - INTERVAL '3 minutes'
        AND r.dtts <= l.latest_time
    GROUP BY 
        l.order_number, l.rider_id
),
oldest_points AS (
    -- Get the details of the oldest location in the window
    SELECT 
        r.order_number,
        r.rider_id,
        r.dtts AS oldest_time,
        r.lat AS oldest_lat,
        r.lon AS oldest_lon
    FROM 
        rider_location r
    JOIN 
        oldest_in_window o ON r.order_number = o.order_number 
                           AND r.rider_id = o.rider_id 
                           AND r.dtts = o.oldest_time
),
location_pairs AS (
    -- Pair the latest and oldest locations for each order
    SELECT 
        l.order_number,
        l.rider_id,
        o.oldest_time,
        l.latest_time,
        o.oldest_lat,
        o.oldest_lon,
        l.latest_lat,
        l.latest_lon
    FROM
        latest_points l
    JOIN
        oldest_points o ON l.order_number = o.order_number AND l.rider_id = o.rider_id
)
-- Calculate the distance using PostgreSQL's spatial functions and return the results
SELECT
    order_number,
    rider_id,
    -- Calculate distance in miles
    ST_Distance(
        -- First point (oldest position)
        ST_SetSRID(ST_MakePoint(oldest_lon, oldest_lat), 4326)::geography,
        -- Second point (latest position)
        ST_SetSRID(ST_MakePoint(latest_lon, latest_lat), 4326)::geography
    ) / 1609.34 AS distance_miles,
    -- Add boolean indicator for distances less than 1 mile
    CASE WHEN ST_Distance(
        ST_SetSRID(ST_MakePoint(oldest_lon, oldest_lat), 4326)::geography,
        ST_SetSRID(ST_MakePoint(latest_lon, latest_lat), 4326)::geography
    ) / 1609.34 < 1 THEN true ELSE false END AS is_less_than_one_mile
FROM
    location_pairs
-- Only include pairs where the coordinates are different (rider has moved)
WHERE
    (oldest_lat <> latest_lat OR oldest_lon <> latest_lon)
ORDER BY
    distance_miles;