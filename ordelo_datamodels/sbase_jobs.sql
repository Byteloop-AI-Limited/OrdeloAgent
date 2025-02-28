DROP FUNCTION get_available_riders(text);
CREATE OR REPLACE FUNCTION get_available_riders(p_order_number text)
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
    WHERE NOT EXISTS 
    (SELECT 1 FROM ridersToExclude WHERE ridersToExclude.rider_id = allRiders.rider_id);
END;
$$ LANGUAGE plpgsql;


INSERT INTO delivery_dispatch(order_number, rider_id, rider_payout, distance, status)
WITH availRider AS (
  SELECT 
  get_available_riders(order_number) as rider_id_to_dispatch, 
  * from delivery_detail where status='unassigned' 
), availRiderCount AS (
  SELECT 
  count(*) as rider_count
  FROM availRider
)
SELECT 
  order_number,
  rider_id_to_dispatch,
  rider_payout,
  distance, 
  availRiderCount.rider_count,
  'unassigned'
FROM availRider
WHERE rider_id_to_dispatch='447448440754'
LIMIT 1;


-- TimeoutUnassignedDispatch
UPDATE delivery_dispatch 
SET status = 'timeout' 
WHERE order_number = 'test123'
AND status = 'unassigned'
AND (current_timestamp - dtts) > interval '30 seconds';