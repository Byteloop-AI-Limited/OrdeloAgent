-- =============================================================================================
-- ordelo_datamodels/dispatch/dispatch_complete_func.sql
-- Mark a delivery completed (dispatch, detail and summary) and remove the live-job row.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     dispatch_complete_func(p_dispatch_id bigint) -> text
--                   Complete the delivery for a dispatch_id; returns 'Order <n> complete'.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call sets delivery_dispatch / delivery_detail / delivery_summary to 'completed' and deletes the delivery_inflight row.
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
--                 Called by the rider agent tool terminate_delivery_job after the customer's code is verified
--                 (ordelo/agents/rider_agent.py), and by the WhatsApp /test utility.
-- LIFECYCLE     none
-- CALLED BY     dispatch_complete_func:
--                 python    ordelo/agents/rider_agent.py: verify_customer_confirmation_code()
--                 python    watomation/on_message_wa_handler.py: reset_thread()
-- PYTHON MODEL  none
-- SECURITY      dispatch_complete_func(): executable by PUBLIC (default)
-- TESTS         tests/ordelo/agents/test_rider_agent.py
--               tests/watomation/test_on_message_wa_handler.py
-- GOTCHAS       none
-- SEE ALSO      dispatch/delivery_inflight.sql
--               test_support/cleanup_delivery_order.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function dispatch_complete_func(p_dispatch_id bigint) -> text
--   Complete the delivery for a dispatch_id; returns 'Order <n> complete'.
--   Data: writes delivery_detail, delivery_dispatch, delivery_inflight, delivery_summary.
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.dispatch_complete_func (p_dispatch_id bigint) IS 'Complete the delivery for a dispatch_id; returns ''Order <n> complete''.';

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
