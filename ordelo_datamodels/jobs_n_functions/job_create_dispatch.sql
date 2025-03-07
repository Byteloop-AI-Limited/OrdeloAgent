/**
Dispatch Creation and Management Process
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

CREATE OR REPLACE FUNCTION job_create_dispatch()
RETURNS void AS $$
DECLARE
  has_unassigned BOOLEAN;
BEGIN
  -- Check if there are any unassigned orders
  SELECT EXISTS (SELECT 1 FROM delivery_detail WHERE status = 'unassigned' LIMIT 1) INTO has_unassigned;
  
  IF has_unassigned THEN
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
        LIMIT 5
        RETURNING order_number
    )
    -- Update delivery_detail for orders with no riders
    UPDATE delivery_detail dd
    SET status = 'timedout'
    FROM availableRiders ar
    WHERE dd.order_number = ar.order_number
    -- AND ar.rider_count = 0
    AND CURRENT_TIMESTAMP - dd.dtts > INTERVAL '30 minutes'
    AND dd.status = 'unassigned'
    AND dd.order_number NOT IN (SELECT order_number FROM dispatch_insert);
    
    RAISE NOTICE 'Processed dispatch creation for unassigned orders.';
  ELSE
    RAISE NOTICE 'No unassigned orders found.';
  END IF;
END;
$$ LANGUAGE plpgsql;

-- To call this function from pgcorn:
-- SELECT job_create_dispatch();

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
