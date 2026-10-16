-- =============================================================================================
-- ordelo_datamodels/dispatch/job_assign_dispatch.sql
-- Every 5 seconds: give each order to the first rider who accepted it.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     job_assign_dispatch() -> TABLE(action text)
--                   For every open order with an accepted dispatch, call assign_accepted_dispatch(); returns the orders it assigned.
--               fn     assign_accepted_dispatch(p_order_number character varying) -> boolean
--                   Assign the order to its first accepted dispatch and create the delivery_inflight row; returns whether anything changed.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each run updates dispatch/detail/summary to 'assigned' and inserts delivery_inflight rows (fires the inflight webhook).
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
-- LIFECYCLE     first 'accepted' dispatch per order (lowest dispatch_id) -> dispatch 'assigned', delivery_detail 'assigned' (rider_id,
--               dispatch_id), delivery_summary 'assigned', new delivery_inflight row.
-- CALLED BY     job_assign_dispatch:
--                 cron      'job_assign_dispatch' 5 seconds
--               assign_accepted_dispatch:
--                 sql       job_assign_delivery() (_orphans/dispatch.sql)
--                 sql       job_assign_dispatch() (dispatch/job_assign_dispatch.sql)
-- PYTHON MODEL  none
-- SECURITY      job_assign_dispatch(): executable by PUBLIC (default)
--               assign_accepted_dispatch(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       Riders' Accept taps only set delivery_dispatch.status = 'accepted' (watomation/on_callback_wa_handler.py); this job decides the winner.
-- SEE ALSO      dispatch/delivery_inflight.sql
--               dispatch/notify_missed_dispatches.sql
--               docs/dispatch_flow.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function job_assign_dispatch() -> TABLE(action text)
--   For every open order with an accepted dispatch, call assign_accepted_dispatch(); returns the orders it assigned.
--   Data: reads delivery_detail; calls assign_accepted_dispatch().
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION job_assign_dispatch ()
    RETURNS TABLE (
        action text
    )
    AS $$
BEGIN
    IF EXISTS (
        SELECT
            1
        FROM
            delivery_detail
        WHERE
            status = 'unassigned'
            OR status = 'vehicle_type_timedout'
        LIMIT 1) THEN
-- Process unassigned orders
PERFORM
    assign_accepted_dispatch (order_number)
FROM
    delivery_detail
WHERE
    status IN ('unassigned', 'vehicle_type_timedout')
ORDER BY
    dtts ASC;
    RETURN QUERY
    SELECT
        'Processed unassigned orders.';
ELSE
    RETURN QUERY
    SELECT
        'No unassigned orders found.';
END IF;
END;
$$
LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------
-- function assign_accepted_dispatch(p_order_number character varying) -> boolean
--   Assign the order to its first accepted dispatch and create the delivery_inflight row; returns whether anything changed.
--   Data: writes delivery_detail, delivery_dispatch, delivery_inflight, delivery_summary.
-- ---------------------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS assign_accepted_dispatch (VARCHAR(100));

CREATE OR REPLACE FUNCTION assign_accepted_dispatch (p_order_number varchar(100))
    RETURNS boolean
    AS $$
DECLARE
    updated boolean := FALSE;
BEGIN
    WITH acceptedDispatches AS (
        SELECT
            *,
            rank() OVER (PARTITION BY order_number ORDER BY dispatch_id ASC) AS dispatch_rank
        FROM
            delivery_dispatch dispatch
        WHERE
            status = 'accepted'
            AND order_number = p_order_number
            AND NOT EXISTS (
                SELECT
                    1
                FROM
                    delivery_inflight
                WHERE
                    rider_id = dispatch.rider_id)
),
acceptedDispatch AS (
    SELECT DISTINCT
        d.dispatch_id,
        d.order_number,
        d.rider_id,
        d.vehicle_type,
        dd.customer_id
    FROM
        acceptedDispatches d
        JOIN delivery_detail dd ON d.order_number = dd.order_number
            AND d.vehicle_type = dd.vehicle_type
    WHERE
        d.dispatch_rank = 1
),
updateDispatch AS (
    UPDATE
        delivery_dispatch
    SET
        status = 'assigned',
        status_update_dtts = CURRENT_TIMESTAMP
    FROM
        acceptedDispatch
    WHERE
        delivery_dispatch.dispatch_id = acceptedDispatch.dispatch_id
    RETURNING
        1
),
updateDetail AS (
    UPDATE
        delivery_detail
    SET
        status = 'assigned',
        dispatch_id = acceptedDispatch.dispatch_id,
        rider_id = acceptedDispatch.rider_id
    FROM
        acceptedDispatch
    WHERE
        delivery_detail.order_number = acceptedDispatch.order_number
        AND delivery_detail.vehicle_type = acceptedDispatch.vehicle_type
    RETURNING
        1
),
updateSummary AS (
    UPDATE
        delivery_summary
    SET
        status = 'assigned'
    FROM
        acceptedDispatch
    WHERE
        delivery_summary.order_number = acceptedDispatch.order_number
    RETURNING
        1
),
insertInflight AS (
INSERT INTO delivery_inflight (dispatch_id, order_number, rider_id, customer_id)
    SELECT
        dispatch_id,
        order_number,
        rider_id,
        customer_id
    FROM
        acceptedDispatch
    RETURNING
        1
)
SELECT
    EXISTS (
        SELECT
            1
        FROM
            updateDetail) INTO updated;
    RETURN updated;
END;
$$
LANGUAGE plpgsql;

-- pg_cron job 'job_assign_dispatch': runs every 5 seconds, active on live.
-- cron.schedule() with an existing job name updates that job in place, so re-running is safe.
SELECT
    cron.schedule ('job_assign_dispatch', '5 seconds', 'SELECT public.job_assign_dispatch()');

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.job_assign_dispatch () IS 'For every open order with an accepted dispatch, call assign_accepted_dispatch(); returns the orders it assigned.';

COMMENT ON FUNCTION public.assign_accepted_dispatch (p_order_number character varying) IS 'Assign the order to its first accepted dispatch and create the delivery_inflight row; returns whether anything changed.';
