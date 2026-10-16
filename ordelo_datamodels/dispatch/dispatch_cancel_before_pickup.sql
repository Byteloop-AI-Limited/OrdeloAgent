-- =============================================================================================
-- ordelo_datamodels/dispatch/dispatch_cancel_before_pickup.sql
-- Rider cancels an assigned job before pickup: free the rider and restart dispatch for the order from scratch.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     dispatch_cancel_before_pickup(p_dispatch_id bigint) -> text
--                   Roll back an assigned, not-yet-collected dispatch and reopen the order for a fresh dispatch round; returns a message.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call: the cancelled dispatch becomes 'declined' (kept, so that rider is never re-offered the order); every other
--               dispatch row and every delivery_detail row of the order is deleted; the inflight row is deleted; delivery_summary goes
--               back to 'unassigned' with redispatch_dtts = now() (fresh timeout window, process_delivery restarts at rank 1).
-- HOW IT FITS   Delivery order journey (statuses in delivery_summary.status unless noted):
--                 1 create   /payment-hooks/payment-complete -> init_delivery() inserts the summary:
--                            'restaurant_unconfirmed', or 'unassigned' with a pickup time when the restaurant auto-accepts.
--                 2 confirm  trigger_restaurant_updates -> POST /delivery-hooks/restaurant-confirmation-request -> admins asked
--                            (WhatsApp buttons; Telegram cards via job_t_order_alerts). restaurant_order_decide() records accept /
--                            decline ('declined' is terminal); restaurant_order_set_pickup() sets pickup_time and 'unassigned'.
--                            process_restaurant_confirmation() (cron 10 s) marks unanswered orders 'restaurant_timedout'; Python then
--                            sets a default pickup time and 'unassigned'.
--                 3 options  process_delivery() (cron 5 s) adds delivery_detail rows, one vehicle type at a time by delivery_option rank,
--                            and marks the summary 'timedout' when every vehicle type timed out (trigger -> /delivery-hooks/delivery-timedout).
--                 4 offers   job_create_dispatch() (cron 5 s) inserts delivery_dispatch offers for available riders
--                            (trigger -> /delivery-hooks/delivery-dispatch -> WhatsApp offer to each rider).
--                 5 assign   a rider taps Accept (dispatch 'accepted'); job_assign_dispatch() (cron 5 s) gives the order to the first
--                            acceptance: dispatch/detail/summary 'assigned' + delivery_inflight row
--                            (trigger -> /delivery-hooks/delivery-inflight-graph-init starts the rider agent; other riders told they missed it).
--                 6 deliver  rider agent: pickup code check ('pickedup'), dispatch_cancel_before_pickup() re-offers the order,
--                            dispatch_complete_func() marks everything 'completed' and removes the inflight row.
--                 Around it: job_rider_pickup_alerts() reminders, kitchen Ready / +10 / +20 (restaurant_admin/), Telegram receipts.
--                 Called by the rider agent tool cancel_delivery_before_pickup (ordelo/agents/rider_agent.py) after the rider gives a reason.
-- LIFECYCLE     only allowed while the dispatch is 'assigned' (returns 'cannot cancel; dispatch status is ...' otherwise).
-- CALLED BY     dispatch_cancel_before_pickup:
--                 python    ordelo/agents/rider_agent.py: cancel_delivery_before_pickup()
-- PYTHON MODEL  none
-- SECURITY      dispatch_cancel_before_pickup(): executable by PUBLIC (default)
-- TESTS         tests/ordelo/agents/test_rider_agent.py
--               tests/regressions/test_p5_regressions.py
-- GOTCHAS       Deleting the other dispatches also deletes their rider_pickup_alert ledgers (ON DELETE CASCADE).
--               A Telegram kitchen receipt becomes stale ('rider_cancelled'); job_t_receipt_refresh replaces it.
-- SEE ALSO      dispatch/job_create_dispatch.sql
--               restaurant_admin/restaurant_ready_adjust_notices.sql (t_receipt_status)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function dispatch_cancel_before_pickup(p_dispatch_id bigint) -> text
--   Roll back an assigned, not-yet-collected dispatch and reopen the order for a fresh dispatch round; returns a message.
--   Data: writes delivery_detail, delivery_dispatch, delivery_inflight, delivery_summary.
-- ---------------------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS dispatch_cancel_before_pickup (bigint);

CREATE OR REPLACE FUNCTION dispatch_cancel_before_pickup (p_dispatch_id bigint)
    RETURNS text
    AS $$
DECLARE
    v_order_number text;
    v_dispatch_status text;
BEGIN
    SELECT
        order_number,
        status INTO v_order_number,
        v_dispatch_status
    FROM
        delivery_dispatch
    WHERE
        dispatch_id = p_dispatch_id
    LIMIT 1;

    IF v_order_number IS NULL THEN
        RETURN 'dispatch not found';
    END IF;
    -- Only allow cancel before pickup (dispatch must still be assigned)
    IF v_dispatch_status <> 'assigned' THEN
        RETURN 'cannot cancel; dispatch status is ' || v_dispatch_status;
    END IF;
    -- Mark dispatch as declined (cancelled before pickup)
    UPDATE
        delivery_dispatch
    SET
        status = 'declined',
        status_update_dtts = CURRENT_TIMESTAMP
    WHERE
        dispatch_id = p_dispatch_id;
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
    UPDATE
        delivery_summary
    SET
        status = 'unassigned',
        redispatch_dtts = NOW()
    WHERE
        order_number = v_order_number
        AND status = 'assigned';

    RETURN 'cancelled dispatch ' || p_dispatch_id || ' for order ' || v_order_number;
END;
$$
LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.dispatch_cancel_before_pickup (p_dispatch_id bigint) IS 'Roll back an assigned, not-yet-collected dispatch and reopen the order for a fresh dispatch round; returns a message.';
