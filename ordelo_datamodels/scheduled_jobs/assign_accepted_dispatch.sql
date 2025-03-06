----------------------------------------
-- assign_accepted_dispatch - Assigns the first accepted dispatch for an order
----------------------------------------
DROP FUNCTION IF EXISTS assign_accepted_dispatch(VARCHAR(100));
CREATE OR REPLACE FUNCTION assign_accepted_dispatch(p_order_number VARCHAR(100))
RETURNS BOOLEAN AS $$
DECLARE
    updated BOOLEAN := FALSE;
BEGIN
    WITH acceptedDispatches AS (
        SELECT 
            * ,
            rank() OVER(PARTITION BY order_number ORDER BY dispatch_id ASC) AS dispatch_rank
        FROM delivery_dispatch dispatch
        WHERE status = 'accepted' AND order_number = p_order_number
        AND NOT EXISTS (
            SELECT 1 FROM delivery_inflight WHERE rider_id = dispatch.rider_id
        )
    ), acceptedDispatch AS (
        SELECT 
            d.dispatch_id, 
            d.order_number, 
            d.rider_id,
            dd.customer_id  
        FROM acceptedDispatches d
        JOIN delivery_detail dd ON d.order_number = dd.order_number
        WHERE d.dispatch_rank = 1
    ), updateDispatch AS (
        UPDATE delivery_dispatch 
        SET status = 'assigned', 
            status_update_dtts = CURRENT_TIMESTAMP
        FROM acceptedDispatch
        WHERE delivery_dispatch.dispatch_id = acceptedDispatch.dispatch_id
        RETURNING 1
    ), updateDetail AS (
        UPDATE delivery_detail 
        SET status = 'assigned', 
            dispatch_id = acceptedDispatch.dispatch_id, 
            rider_id = acceptedDispatch.rider_id
        FROM acceptedDispatch
        WHERE delivery_detail.order_number = acceptedDispatch.order_number
        RETURNING 1
    ), insertInflight AS (
        INSERT INTO delivery_inflight (
            dispatch_id, order_number, rider_id, customer_id
        )
        SELECT 
            dispatch_id, 
            order_number, 
            rider_id, 
            customer_id
        FROM acceptedDispatch
        RETURNING 1
    )
    SELECT EXISTS (SELECT 1 FROM updateDetail) INTO updated;
    RETURN updated;
END;
$$ LANGUAGE plpgsql;

