WITH allRiders AS (
  SELECT DISTINCT rider_id FROM rider_master
  UNION
  SELECT DISTINCT rider_id FROM delivery_inflight
), unassignedOrders AS (
  SELECT DISTINCT order_number FROM delivery_detail WHERE status='unassigned'
), ridersToExclude AS (
  SELECT DISTINCT rider_id FROM delivery_dispatch dDispatch
  WHERE EXISTS (SELECT 1 FROM unassignedOrders WHERE order_number=dDispatch.order_number)
)
select * from ridersToExclude;

-- Woop Loop
DROP FUNCTION get_available_riders(text);
CREATE OR REPLACE FUNCTION get_available_riders(p_order_number text)
RETURNS TABLE(rider_id VARCHAR(12), order_number text) AS $$
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
        allRiders.rider_id, 
        p_order_number AS order_number
    FROM rider_master allRiders 
    WHERE NOT EXISTS 
    (SELECT 1 FROM ridersToExclude WHERE ridersToExclude.rider_id = allRiders.rider_id);
END;
$$ LANGUAGE plpgsql;


SELECT get_available_riders(order_number), * from delivery_detail where status='unassigned';