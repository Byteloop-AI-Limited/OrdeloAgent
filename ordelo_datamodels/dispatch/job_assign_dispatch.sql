/**
Dispatch Assignment – Step 4 in Delivery Workflow

Where This Fits in the Journey:
    - This function is the fourth step in the delivery agent workflow, as outlined in handwritten_design.md.
    - Step 1: init_delivery – Creates delivery_summary and calls process_delivery().
    - Step 2: process_delivery – Creates delivery_detail records and manages assignment/timeouts.
    - Step 3: job_create_dispatch – Creates dispatches for available riders, updates statuses.
    - Step 4: job_assign_dispatch – Assigns dispatches to riders who have accepted, updates statuses, and inserts into delivery_inflight to kick off rider graph and notifications.
    - Step 5+: Downstream jobs and triggers handle inflight tracking and notifications.

Invocation:
    - Scheduled cron job 'job_assign_dispatch' (typically every 5–10 seconds).
    - Operates on all unassigned or vehicle_type_timedout delivery_detail records.

Purpose:
    - Look for accepted dispatches and assign based on the first accepted dispatch per order.
    - Update the statuses of dispatch, detail, and summary tables accordingly.
    - Insert into delivery_inflight, which kicks off the rider graph and notification of missed dispatches.

Dependencies:
    - Reads from: `delivery_detail`, `delivery_dispatch` (for status and acceptance), and uses assign_accepted_dispatch().
    - Writes to: `delivery_dispatch`, `delivery_detail`, `delivery_summary`, `delivery_inflight`.

Side Effects:
    1. Inserts into delivery_inflight, kicking off rider graph and notification of missed dispatches.
    2. Sends WhatsApp messages to riders with delivery summaries.
    3. Enables downstream inflight and notification jobs.

See also: jobs_n_functions/handwritten_design.md for the full delivery journey.
**/
CREATE OR REPLACE FUNCTION job_assign_dispatch()
RETURNS TABLE(action TEXT) AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM delivery_detail WHERE status = 'unassigned' or status = 'vehicle_type_timedout' LIMIT 1) THEN
    -- Process unassigned orders
    PERFORM assign_accepted_dispatch(order_number)
    FROM delivery_detail
    WHERE status IN ('unassigned','vehicle_type_timedout')
    ORDER BY dtts ASC;
    RETURN QUERY SELECT 'Processed unassigned orders.';
  ELSE
    RETURN QUERY SELECT 'No unassigned orders found.';
  END IF;
END;
$$ LANGUAGE plpgsql;

-- To call this function from pgcorn:
-- SELECT job_assign_dispatch();
----------------------------------------
-- assign_accepted_dispatch - Assigns the first accepted dispatch for an order
-- Delivery dispatch status is updated to accepted in the initial handle of rider response thats run by on_callback `dispatch_response`
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
    ), updateSummary AS (
        UPDATE delivery_summary 
        SET status = 'assigned'
        FROM acceptedDispatch
        WHERE delivery_summary.order_number = acceptedDispatch.order_number
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

-- pg_cron job 'job_assign_dispatch' (live schedule: 5 seconds, active). cron.schedule() updates the job in place when the name already exists.
SELECT cron.schedule('job_assign_dispatch', '5 seconds', $cron$SELECT public.job_assign_dispatch()$cron$);
