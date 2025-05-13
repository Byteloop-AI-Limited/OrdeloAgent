CREATE OR REPLACE FUNCTION process_delivery()
  RETURNS TABLE(action TEXT)
  LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  WITH deliverySnapShot AS (
    SELECT
      summ.order_number,
      summ.customer_id,
      det.vehicle_type   AS detail_vehicle_type,
      det.status         AS detail_vehicle_status,
      dopt.rank          AS available_vehicle_rank,
      dopt.vehicle_type  AS available_vehicle_type,
      summ.town,
      dopt.driver_payout as rider_payout,
      (dopt.breakdown::JSON ->> 'distance_miles')::DOUBLE precision as distance,
      rank() OVER (
        PARTITION BY summ.order_number
        ORDER BY det.status   ASC NULLS FIRST,
                 dopt.rank     ASC
      )                    AS next_vehicle_rank
    FROM delivery_summary summ
    JOIN delivery_option  dopt
      ON dopt.order_number = summ.order_number
    LEFT JOIN delivery_detail det
      ON det.order_number   = summ.order_number
     AND det.vehicle_type   = dopt.vehicle_type
    WHERE summ.status = 'unassigned'
  )
  , timedout_orders AS (
    -- which orders have *all* vehicles timed-out?
    SELECT order_number
      FROM deliverySnapShot
     GROUP BY order_number
    HAVING MAX(available_vehicle_rank)
         = SUM( (detail_vehicle_status = 'vehicle_type_timedout')::int )
  )
  , update_summary AS (
    -- mark those orders as timed-out
    UPDATE delivery_summary ds
       SET status = 'timedout'
      FROM timedout_orders t
     WHERE ds.order_number = t.order_number
       AND ds.status       = 'unassigned'
    RETURNING
      'Order ' || ds.order_number || ' → status set to timeout'
        AS action
  )
  , to_insert AS (
    -- which un‐assigned orders where all existing details are timed-out
    SELECT 
      order_number, 
      customer_id, 
      available_vehicle_type,
      town,
      rider_payout,
      distance
      FROM deliverySnapShot ds_outer
     WHERE ds_outer.next_vehicle_rank = 1
       AND ds_outer.detail_vehicle_status IS NULL
       AND NOT EXISTS (
         SELECT 1
           FROM deliverySnapShot ds2
          WHERE ds2.order_number = ds_outer.order_number
            AND ds2.detail_vehicle_status IS NOT NULL
            AND ds2.detail_vehicle_status <> 'vehicle_type_timedout'
       )
  )
  , insert_details AS (
    -- insert exactly that “next” vehicle as a new detail row
    INSERT INTO delivery_detail(
        order_number,
        customer_id,
        vehicle_type,
        town,
        rider_payout,
        distance,
        status
    )
    SELECT order_number,
           customer_id,
           available_vehicle_type,
           town,
           rider_payout,
           distance,
           'unassigned'
      FROM to_insert
    RETURNING
      'Order ' || order_number
        || ' → inserted detail for vehicle_type '
        || vehicle_type
        AS action
  )
  -- finally stitch the two logs together
  SELECT us.action FROM update_summary us
  UNION ALL
  SELECT id.action FROM insert_details id
  ;
END;
$$;
-- - Change delivery_detail structure; Dont need insert_delivery_detail function, can just be insert into in the manage_delivery_detail function