/**
Delivery Detail Management – Step 2 in Delivery Workflow
IMP - Below had to be set at db level to avoid failures
SET http.timeout TO '15s';
Where This Fits in the Journey:
    - This function is the second step in the delivery agent workflow, as outlined in handwritten_design.md.
    - Step 1: init_delivery – Creates delivery_summary and calls process_delivery().
    - Step 2: process_delivery – Creates delivery_detail records for each vehicle type, manages assignment, timeouts, and triggers further workflow.
    - Step 3+: Downstream jobs (e.g., job_create_dispatch) and triggers handle dispatch creation, assignment, inflight tracking, and notifications.

Invocation:
    - Scheduled via pg_cron job manage_delivery_detail() every 5 seconds, or called eagerly by init_delivery().

Purpose:
    - Manage assignment and timeout of `delivery_detail` records per order.
    - Prioritize vehicle types based on rank from `delivery_option`.
    - Insert next eligible `delivery_detail` when timeouts occur.
    - Mark orders as `timedout` in `delivery_summary` when all vehicle types have timed out and the time delta exceeds DELIVERY_TIMEOUT_TIME (from ordelo_config).
    - DELIVERY_TIMEOUT_TIME is obtained from ordelo_config with config_key = 'delivery_timeout_TIME'.
    - The status for this table is updated to `vehicle_type_timedout` by downstream jobs.

Dependencies:
    - Reads from: `delivery_summary`, `delivery_detail`, `delivery_option`, `ordelo_config`.
    - Writes to: `delivery_detail`, `delivery_summary`.

Side Effects:
    1. Insert new `delivery_detail` rows.
    2. Update `delivery_summary` statuses.
    3. Triggers downstream workflow (e.g., dispatch creation, notifications).

See also: jobs_n_functions/handwritten_design.md for the full delivery journey.
**/
CREATE OR REPLACE FUNCTION process_delivery() RETURNS TABLE(action TEXT) LANGUAGE plpgsql AS $$
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
    -- mmark those orders as timed-outark those orders as timed-out
    UPDATE delivery_summary ds
       SET status = 'timedout'
      FROM timedout_orders t,
           (SELECT config_value::int AS timeout_minutes FROM ordelo_config WHERE config_key = 'DELIVERY_TIMEOUT_TIME') cfg
     WHERE ds.order_number = t.order_number
       AND ds.status       = 'unassigned'
       AND (EXTRACT(EPOCH FROM (NOW() - ds.dtts))/60) > cfg.timeout_minutes
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

-- Create a trigger for when the status of delivery_summary changes to 'timedout'

CREATE TRIGGER trigger_delivery_summary_timedout AFTER
UPDATE ON public.delivery_summary
FOR EACH ROW WHEN (OLD.status <> 'timedout'
                   AND NEW.status = 'timedout') EXECUTE FUNCTION public.delivery_summary_timedout_whook();

-- delivery_summary_timedout_whook function

/*
Delivery Summary Timedout Webhook Trigger
  . Fetches the base app URL from ordelo_config (key: ORDELO_APP_URL)
  . Constructs the webhook URL by appending '/delivery-hooks/delivery-timedout'
  . Constructs JSON payload from NEW record
  . Makes HTTP POST to the constructed webhook URL
  . Logs the response
  . Returns NEW for trigger continuation
Functions:
  . delivery_summary_timedout_whook
*/
CREATE OR REPLACE FUNCTION public.delivery_summary_timedout_whook() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  response json;
  webhook_payload json;
  ordelo_app_url text;
  webhook_url text;
BEGIN
  -- Combine the NEW record with additional data from delivery_detail; required to invoke graph
  SELECT json_build_object(
    'delivery_summary', json_build_array(row_to_json(NEW))
  ) INTO webhook_payload;

  -- Fetch the base app URL from config, fallback to default if not present
  SELECT config_value INTO ordelo_app_url FROM ordelo_config WHERE config_key = 'ORDELO_APP_URL';
  IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
    ordelo_app_url := 'https://rider-agent.ordelo.app';
  END IF;
  webhook_url := ordelo_app_url || '/delivery-hooks/delivery-timedout';

  -- Make the HTTP POST request with the combined payload
  response := (
    SELECT content
    FROM http_post(
      webhook_url,
      webhook_payload::text,
      'application/json'
    )
  );

  -- Log the response
  RAISE NOTICE 'Response from HTTP POST to delivery-timedout: %', response;

  RETURN NEW;
END;
$$;