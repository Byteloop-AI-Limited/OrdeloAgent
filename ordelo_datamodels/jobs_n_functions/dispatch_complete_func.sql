/**
Complete a dispatch (Complete the delivery process)

Invocation:
1. Called by agent when delivery is complete
2. Used by test

Purpose:
- Updates the dispatch, detail and summary table with status='completed', 
- Removes the inflight record

Side Effects:
None
**/

----------------------------------------
-- dispatch_complete_func - Completes a dispatch
----------------------------------------

DROP FUNCTION IF EXISTS dispatch_complete_func(bigint);
CREATE OR REPLACE FUNCTION dispatch_complete_func(p_dispatch_id bigint)
RETURNS TEXT AS $$
DECLARE
    v_order_number TEXT;
BEGIN
    -- Get the order number for this dispatch
    SELECT DISTINCT order_number INTO v_order_number
    FROM delivery_detail
    WHERE dispatch_id = p_dispatch_id
    LIMIT 1;

    -- Update delivery_dispatch status
    UPDATE delivery_dispatch 
    SET status = 'completed' 
    WHERE delivery_dispatch.dispatch_id = p_dispatch_id;

    -- Update delivery_detail status
    UPDATE delivery_detail 
    SET status = 'completed' 
    WHERE delivery_detail.dispatch_id = p_dispatch_id;

    -- Update delivery_summary status
    UPDATE delivery_summary
    SET status = 'completed'
    WHERE order_number = v_order_number;

    -- Update delivery_inflight status
    DELETE FROM delivery_inflight  
    WHERE delivery_inflight.dispatch_id = p_dispatch_id;

    RETURN 'Order ' || v_order_number || ' complete';
END;
$$ LANGUAGE plpgsql;


----------------------------------------
-- TimeoutUnassignedDispatch
----------------------------------------
UPDATE delivery_dispatch 
SET status = 'timedout' 
WHERE status = 'unassigned'
AND (current_timestamp - dtts) > interval '30 seconds';