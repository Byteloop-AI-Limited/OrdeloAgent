/**
Dispatch Cancel Before Pickup – Resume Dispatch Workflow

Where This Fits in the Journey:
    - Used when an assigned rider declines/cancels a job *before* pickup is confirmed.
    - Pickup confirmation is tracked via delivery_dispatch.status = 'pickedup'.
    - If cancelled while status='assigned', the order is reopened for dispatch.

Invocation:
    - Called by rider agent/tool via Supabase RPC: dispatch_cancel_before_pickup(p_dispatch_id).

Purpose:
    - Safely roll back an assigned (but not picked up) dispatch.
    - Resume dispatch flow by reverting delivery_detail and delivery_summary to 'unassigned'.

Dependencies:
    - Reads from: delivery_dispatch, delivery_detail, delivery_summary, delivery_inflight.
    - Writes to: delivery_dispatch, delivery_detail, delivery_summary, delivery_inflight (delete).

Side Effects:
    1. Marks the cancelled dispatch as 'declined'.
    2. Deletes the inflight record for the dispatch.
    3. Reopens the delivery_detail and delivery_summary for fresh dispatching.
**/

DROP FUNCTION IF EXISTS dispatch_cancel_before_pickup(bigint);

CREATE OR REPLACE FUNCTION dispatch_cancel_before_pickup(p_dispatch_id bigint)
RETURNS TEXT AS $$
DECLARE
    v_order_number TEXT;
    v_vehicle_type TEXT;
    v_dispatch_status TEXT;
BEGIN
    SELECT order_number, vehicle_type, status
      INTO v_order_number, v_vehicle_type, v_dispatch_status
      FROM delivery_dispatch
     WHERE dispatch_id = p_dispatch_id
     LIMIT 1;

    IF v_order_number IS NULL THEN
        RETURN 'dispatch not found';
    END IF;

    -- Only allow cancel before pickup (dispatch must still be assigned)
    IF v_dispatch_status <> 'assigned' THEN
        RETURN 'cannot cancel; dispatch status is ' || v_dispatch_status;
    END IF;

    -- Mark dispatch as declined (cancelled before pickup)
    UPDATE delivery_dispatch
       SET status = 'declined',
           status_update_dtts = CURRENT_TIMESTAMP
     WHERE dispatch_id = p_dispatch_id;

    -- Remove inflight record so rider is freed for new jobs
    DELETE FROM delivery_inflight
     WHERE dispatch_id = p_dispatch_id;

    -- Reopen the assigned detail row for re-dispatch
    UPDATE delivery_detail
       SET status = 'unassigned',
           dispatch_id = NULL,
           rider_id = NULL
     WHERE order_number = v_order_number
       AND vehicle_type = v_vehicle_type
       AND status = 'assigned';

    -- Reopen summary so downstream jobs pick it up again
    UPDATE delivery_summary
       SET status = 'unassigned'
     WHERE order_number = v_order_number
       AND status = 'assigned';

    RETURN 'cancelled dispatch ' || p_dispatch_id || ' for order ' || v_order_number;
END;
$$ LANGUAGE plpgsql;

