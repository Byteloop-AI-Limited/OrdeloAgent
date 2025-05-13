/**
Assigning Delivery to Riders who have accepted the job.
This is dependent on `assign_accepted_dispatch` function
Invocation:
1. Scheduled cron job 'create_dispatch_for_unassigned_orders' (10s interval)

Purpose:
- Manage unassigned orders
- Create new dispatch entries based on available riders (function - get_available_riders())
- Update delivery_detail with timeout status

Execution:
- Frequency: Every 5 seconds

Side Effects:
1. Trigger webhook: /delivery-hooks/delivery-dispatch on insert
2. Send WhatsApp messages to riders with delivery summaries
**/

CREATE OR REPLACE FUNCTION job_assign_dispatch()
RETURNS void AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM delivery_detail WHERE status = 'unassigned' or status = 'vehicle_type_timedout' LIMIT 1) THEN
    -- Process unassigned orders
    PERFORM assign_accepted_dispatch(order_number) 
    FROM delivery_detail 
    WHERE status='unassigned' or status = 'vehicle_type_timedout'
    ORDER BY dtts ASC;
    RAISE NOTICE 'Processed unassigned orders.';
  ELSE
    RAISE NOTICE 'No unassigned orders found.';
  END IF;
END;
$$ LANGUAGE plpgsql;

-- To call this function from pgcorn:
-- SELECT job_assign_dispatch();
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
        SELECT DISTINCT
            d.dispatch_id, 
            d.order_number, 
            d.rider_id,
            d.vehicle_type,
            dd.customer_id  
        FROM acceptedDispatches d
        JOIN delivery_detail dd ON d.order_number = dd.order_number and d.vehicle_type = dd.vehicle_type
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
        WHERE delivery_detail.order_number = acceptedDispatch.order_number and delivery_detail.vehicle_type = acceptedDispatch.vehicle_type
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