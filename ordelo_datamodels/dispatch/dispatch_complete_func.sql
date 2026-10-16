/**
Dispatch Completion – Final Step in Delivery Workflow

Where This Fits in the Journey:
    - This function is the final step in the delivery agent workflow, as outlined in handwritten_design.md.
    - Step 1: init_delivery – Creates delivery_summary and calls process_delivery().
    - Step 2: process_delivery – Creates delivery_detail records and manages assignment/timeouts.
    - Step 3: job_create_dispatch – Creates dispatches for available riders, updates statuses.
    - Step 4: job_assign_dispatch – Assigns dispatches to riders who have accepted, updates statuses, and inserts into delivery_inflight.
    - Step 5: delivery_inflight_whook – Kicks off rider graph and missed dispatch notifications.
    - Step 6: dispatch_complete_func (this function) – Marks dispatch, detail, and summary as completed and removes inflight record.

Invocation:
    - Called by agent (on customer confirmation code) when delivery is complete.
    - Used by test routines for delivery completion.

Purpose:
    - Update the dispatch, detail, and summary tables with status='completed'.
    - Remove the inflight record associated with the completed dispatch.

Dependencies:
    - Reads from: `delivery_detail`, `delivery_dispatch`, `delivery_summary`, `delivery_inflight`.
    - Writes to: `delivery_dispatch`, `delivery_detail`, `delivery_summary`, `delivery_inflight` (delete).

Side Effects:
    1. Removes the inflight record for the completed dispatch.
    2. Finalizes the order in all workflow tables.
    3. Enables downstream reporting and archival jobs.

See also: jobs_n_functions/handwritten_design.md for the full delivery journey.
**/

----------------------------------------
-- dispatch_complete_func - Completes a dispatch
----------------------------------------
DROP FUNCTION IF EXISTS dispatch_complete_func (bigint);

CREATE OR REPLACE FUNCTION dispatch_complete_func (p_dispatch_id bigint)
    RETURNS text
    AS $$
DECLARE
    v_order_number text;
BEGIN
    -- Get the order number for this dispatch
    SELECT DISTINCT
        order_number INTO v_order_number
    FROM
        delivery_detail
    WHERE
        dispatch_id = p_dispatch_id
    LIMIT 1;
    -- Update delivery_dispatch status
    UPDATE
        delivery_dispatch
    SET
        status = 'completed'
    WHERE
        delivery_dispatch.dispatch_id = p_dispatch_id;
    -- Update delivery_detail status
    UPDATE
        delivery_detail
    SET
        status = 'completed'
    WHERE
        delivery_detail.dispatch_id = p_dispatch_id;
    -- Update delivery_summary status
    UPDATE
        delivery_summary
    SET
        status = 'completed'
    WHERE
        order_number = v_order_number;
    -- Update delivery_inflight status
    DELETE FROM delivery_inflight
    WHERE delivery_inflight.dispatch_id = p_dispatch_id;

    RETURN 'Order ' || v_order_number || ' complete';
END;
$$
LANGUAGE plpgsql;

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

----------------------------------------
-- TimeoutUnassignedDispatch
----------------------------------------
-- UPDATE delivery_dispatch 
-- SET status = 'timedout' 
-- WHERE status = 'unassigned'
-- AND (current_timestamp - dtts) > interval '30 seconds';

-- dispatch_complete_func
