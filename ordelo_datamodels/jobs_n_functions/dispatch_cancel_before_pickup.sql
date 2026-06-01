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
    - Re-broadcast on next cron tick: every vehicle_type for the order is reopened
      (both 'assigned' and 'vehicle_type_timedout' rows flipped to 'unassigned'),
      so job_create_dispatch fans out across all vehicle_type rider pools in parallel.
    - Reset the delivery-timeout clock by stamping delivery_summary.redispatch_dtts =
      NOW(); process_delivery uses COALESCE(redispatch_dtts, dtts) as the timeout base,
      giving the re-dispatch a full timeout window.
    - The declining rider is automatically excluded from future dispatches for this
      order by get_available_riders (which filters out any rider already present in
      delivery_dispatch for the order_number, regardless of status).

Dependencies:
    - Reads from: delivery_dispatch, delivery_detail, delivery_summary, delivery_inflight.
    - Writes to: delivery_dispatch, delivery_detail, delivery_summary, delivery_inflight (delete).

Side Effects:
    1. Marks the cancelled dispatch as 'declined'.
    2. Deletes the inflight record for the dispatch.
    3. Reopens ALL delivery_detail rows for the order (assigned + vehicle_type_timedout)
       so re-dispatch broadcasts simultaneously across every vehicle_type.
    4. Reopens delivery_summary and resets redispatch_dtts to NOW().
**/

DROP FUNCTION IF EXISTS dispatch_cancel_before_pickup(bigint);

CREATE OR REPLACE FUNCTION dispatch_cancel_before_pickup(p_dispatch_id bigint)
RETURNS TEXT AS $$
DECLARE
    v_order_number TEXT;
    v_dispatch_status TEXT;
BEGIN
    SELECT order_number, status
      INTO v_order_number, v_dispatch_status
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

    
    -- delete all entries from delivery_dispatch for the order, except dispatch_id = p_dispatch_id; 
    -- Otherwise, get_available_riders will return the earlier dispatches as riders to exclude, hence repeated notifications will not be sent.
    DELETE FROM delivery_dispatch
     WHERE order_number = v_order_number
       AND dispatch_id <> p_dispatch_id;
    
    -- Reopen ALL detail rows for the order — both the just-cancelled 'assigned'
    -- row and any vehicle_types that had previously timed out. job_create_dispatch
    -- will then go through the dispatch flow from the start. get_available_riders will handle the logic of not sending the same notification to the  rider who declined.
    DELETE FROM delivery_detail
     WHERE order_number = v_order_number;

    -- Reopen summary so downstream jobs pick it up again, and reset the
    -- delivery-timeout clock so the re-dispatch gets a full timeout window.
    UPDATE delivery_summary
       SET status = 'unassigned',
           redispatch_dtts = NOW()
     WHERE order_number = v_order_number
       AND status = 'assigned';

    RETURN 'cancelled dispatch ' || p_dispatch_id || ' for order ' || v_order_number;
END;
$$ LANGUAGE plpgsql;

