----------------------------------------
-- Summary of functions in this file
/**
- get_available_riders(p_order_number text, p_town text DEFAULT 'basingstoke'): 
    Gets available riders for a given order number and town.
- dispatch_accept_func(p_dispatch_id bigint): Create required db records when rider accepts a dispatch.
- dispatch_complete_func: Completes a dispatch.
- assign_accepted_dispatch(p_order_number VARCHAR(100)): Assigns the first accepted dispatch for an order.
**/
----------------------------------------

----------------------------------------
-- Get available riders for a given order number and town
----------------------------------------
DROP FUNCTION IF EXISTS get_available_riders(text, text);
CREATE OR REPLACE FUNCTION get_available_riders(p_order_number text, p_town text DEFAULT 'basingstoke')
RETURNS TABLE(rider_id VARCHAR(12)) AS $$
BEGIN
    RETURN QUERY
    WITH ridersToExclude AS (
        SELECT DISTINCT dDispatch.rider_id 
        FROM delivery_dispatch dDispatch
        WHERE dDispatch.order_number = p_order_number
        UNION 
        SELECT DISTINCT inflight.rider_id 
        FROM delivery_inflight inflight
    )
    SELECT 
        allRiders.rider_id
    FROM rider_master allRiders 
    WHERE 
    LOWER(allRiders.town)=LOWER(p_town) AND NOT EXISTS 
    (SELECT 1 FROM ridersToExclude WHERE ridersToExclude.rider_id = allRiders.rider_id);

END;
$$ LANGUAGE plpgsql;

----------------------------------------
-- Create dispatch OR update delivery_detail with timeout
----------------------------------------
WITH availableRiders AS (
    SELECT 
        dd.order_number,
        gar.rider_id as rider_id_to_dispatch,
        dd.rider_payout,
        dd.distance,
        COUNT(gar.rider_id) as rider_count
    FROM delivery_detail dd
    LEFT JOIN LATERAL get_available_riders(dd.order_number) gar ON true
    WHERE dd.status = 'unassigned'
    GROUP BY dd.order_number, dd.rider_payout, dd.distance, gar.rider_id
), dispatch_insert AS (
    -- Insert for orders with available riders
    INSERT INTO delivery_dispatch(order_number, rider_id, rider_payout, distance, status)
    SELECT 
        order_number,
        rider_id_to_dispatch,
        rider_payout,
        distance,
        'unassigned'
    FROM availableRiders
    WHERE rider_count > 0
    LIMIT 1
    RETURNING order_number
)
-- Update delivery_detail for orders with no riders
UPDATE delivery_detail dd
SET status = 'timedout'
FROM availableRiders ar
WHERE dd.order_number = ar.order_number
AND ar.rider_count = 0
AND dd.status = 'unassigned'
AND dd.order_number NOT IN (SELECT order_number FROM dispatch_insert);

----------------------------------------
-- TimeoutUnassignedDispatch
----------------------------------------
UPDATE delivery_dispatch 
SET status = 'timedout' 
WHERE status = 'unassigned'
AND (current_timestamp - dtts) > interval '30 seconds';

----------------------------------------
-- dispatch_accept_func, return detail record for further use
----------------------------------------
DROP FUNCTION IF EXISTS dispatch_accept_func(bigint, VARCHAR(100), VARCHAR(12));
CREATE OR REPLACE FUNCTION dispatch_accept_func(
    p_dispatch_id BIGINT, 
    p_order_number VARCHAR(100), 
    p_rider_id VARCHAR(12)
    )
RETURNS json AS $$
DECLARE
    result_json json;
BEGIN
    -- Update delivery_dispatch status and status_update_dtts
    UPDATE delivery_dispatch 
    SET status = 'assigned', 
        status_update_dtts = CURRENT_TIMESTAMP
    WHERE dispatch_id = p_dispatch_id;

    -- Update delivery_detail status, dispatch_id and rider_id
    UPDATE delivery_detail 
    SET status = 'assigned', 
        dispatch_id = p_dispatch_id, 
        rider_id = p_rider_id
    WHERE order_number = p_order_number;

    -- Insert into delivery_inflight
    INSERT INTO delivery_inflight (dispatch_id, order_number, rider_id, customer_id)
    VALUES (p_dispatch_id, p_order_number, p_rider_id, (SELECT customer_id FROM delivery_detail WHERE order_number = p_order_number));

    -- Get the record as JSON
    SELECT row_to_json(detail) INTO result_json
    FROM (
        SELECT 
            order_number,
            rider_payout,
            distance,
            rest_id, 
            rest_name,
            rest_lon,
            rest_lat,
            rest_address,
            town,
            customer_id, 
            customer_name,
            customer_lon,
            customer_lat,
            customer_address,
            status,
            dispatch_id,
            rider_id,
            dt,
            dtts
        FROM delivery_detail 
        WHERE delivery_detail.dispatch_id = p_dispatch_id
        LIMIT 1
    ) detail;

    RETURN result_json;
END;
$$ LANGUAGE plpgsql;

----------------------------------------
-- dispatch_complete_func
----------------------------------------

DROP FUNCTION IF EXISTS dispatch_complete_func(bigint);
CREATE OR REPLACE FUNCTION dispatch_complete_func(p_dispatch_id bigint)
RETURNS BOOLEAN AS $$
BEGIN
    -- Update delivery_dispatch status
    UPDATE delivery_dispatch 
    SET status = 'completed' 
    WHERE delivery_dispatch.dispatch_id = p_dispatch_id;

    -- Update delivery_detail status
    UPDATE delivery_detail 
    SET status = 'completed' 
    WHERE delivery_detail.dispatch_id = p_dispatch_id;

    -- Update delivery_inflight status
    DELETE FROM delivery_inflight  
    WHERE delivery_inflight.dispatch_id = p_dispatch_id;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;