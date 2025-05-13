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
RETURNS TABLE(action TEXT)
AS $$
DECLARE
  has_unassigned BOOLEAN;
BEGIN
  SELECT EXISTS (SELECT 1 FROM delivery_detail WHERE status = 'unassigned' LIMIT 1) INTO has_unassigned;
  
  IF has_unassigned THEN
    RETURN QUERY
    WITH availableRiders AS (
        SELECT 
            dd.order_number,
            gar.rider_id as rider_id_to_dispatch,
            dd.rider_payout,
            dd.distance,
            dd.vehicle_type,
            COUNT(gar.rider_id) as rider_count
        FROM delivery_detail dd
        LEFT JOIN LATERAL get_available_riders(dd.order_number, LOWER(dd.town), dd.vehicle_type) gar ON true
        WHERE dd.status = 'unassigned'
        GROUP BY dd.order_number, dd.rider_payout, dd.distance, dd.vehicle_type, gar.rider_id
    ), dispatch_candidates AS (
        SELECT ar.order_number,
               ar.rider_id_to_dispatch,
               ar.rider_payout,
               ar.distance,
               ar.vehicle_type,
               ar.rider_count,
               COALESCE(oc.config_value::int, 1) AS batch_size,
               row_number() OVER (PARTITION BY ar.vehicle_type ORDER BY ar.order_number) AS rn
        FROM availableRiders ar
        LEFT JOIN ordelo_config oc
          ON oc.config_key = 'DISPATCH_BATCH_SIZE_' || UPPER(ar.vehicle_type)
    ), dispatch_insert AS (
        INSERT INTO delivery_dispatch (order_number, rider_id, rider_payout, distance, vehicle_type, status)
        SELECT 
            order_number,
            rider_id_to_dispatch,
            rider_payout,
            distance,
            vehicle_type,
            'unassigned'
        FROM dispatch_candidates 
        WHERE rider_count > 0
          AND rn <= batch_size
        RETURNING
          'Order ' || order_number || ' → dispatch created for rider ' || rider_id AS action,
          order_number
    ), update_detail_logs AS (
        UPDATE delivery_detail dd
        SET status = 'vehicle_type_timedout'
        FROM availableRiders ar
        WHERE dd.order_number = ar.order_number
          AND dd.status = 'unassigned'
          AND dd.order_number NOT IN (SELECT di.order_number FROM dispatch_insert di)
        RETURNING
          'Order ' || dd.order_number || ' → status set to vehicle_type_timedout' AS action
    )
    SELECT di.action FROM dispatch_insert di
    UNION ALL
    SELECT ul.action FROM update_detail_logs ul;
  ELSE
    RETURN QUERY SELECT 'No unassigned orders found.'::text AS action;
  END IF;
END;
$$ LANGUAGE plpgsql;

----------------------------------------
-- Get available riders for a given order number and town
----------------------------------------
DROP FUNCTION IF EXISTS get_available_riders(text, text, text);
CREATE OR REPLACE FUNCTION get_available_riders(p_order_number text, p_town text, p_vehicle_type text)
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
    LOWER(allRiders.town)=LOWER(p_town)
    AND allRiders.vehicle_type = p_vehicle_type
    AND allRiders.is_in_shift
    AND NOT EXISTS 
    (SELECT 1 FROM ridersToExclude WHERE ridersToExclude.rider_id = allRiders.rider_id);

END;
$$ LANGUAGE plpgsql;
