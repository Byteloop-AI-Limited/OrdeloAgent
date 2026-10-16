-- =============================================================================================
-- ordelo_datamodels/delivery/process_delivery.sql
-- Every 5 seconds: add delivery_detail rows (vehicle-type options) for dispatchable orders and time out orders with no rider.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     process_delivery() -> TABLE(action text)
--                   Advance every unassigned delivery: open the next vehicle-type option or time the order out; returns what it changed.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each run inserts delivery_detail rows and may set delivery_summary.status = 'timedout' (fires the timed-out webhook).
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
-- LIFECYCLE     For each delivery_summary in 'unassigned': if no delivery_detail is open, insert one for the next vehicle type by
--               delivery_option.rank (starting with rank 1). When every ranked vehicle type is 'vehicle_type_timedout' and the order is
--               older than <REST>_DELIVERY_TIMEOUT_TIME (else DELIVERY_TIMEOUT_TIME, else 10 minutes), set the summary to 'timedout'.
-- CALLED BY     process_delivery:
--                 cron      'process_delivery' 5 seconds
--                 sql       handle_restaurant_confirmation() (_orphans/restaurant_admin.sql)
-- PYTHON MODEL  none
-- SECURITY      process_delivery(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       The cron job is called 'process_delivery' (older docs call it 'manage_delivery_detail').
--               Comments in older versions: 'SET http.timeout TO 15s' had to be set at database level to avoid failures.
-- SEE ALSO      delivery/delivery_detail.sql
--               delivery/delivery_option.sql
--               dispatch/job_create_dispatch.sql
--               docs/delivery_process.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function process_delivery() -> TABLE(action text)
--   Advance every unassigned delivery: open the next vehicle-type option or time the order out; returns what it changed.
--   Reads delivery_summary, delivery_detail, delivery_option and ordelo_config; writes delivery_detail and delivery_summary.
--   Data: reads delivery_option, ordelo_config; writes delivery_detail, delivery_summary.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION process_delivery ()
    RETURNS TABLE (
        action text)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY WITH deliverySnapShot AS (
        SELECT
            summ.order_number,
            summ.customer_id,
            det.vehicle_type AS detail_vehicle_type,
            det.status AS detail_vehicle_status,
            dopt.rank AS available_vehicle_rank,
            dopt.vehicle_type AS available_vehicle_type,
            summ.town,
            dopt.driver_payout AS rider_payout,
            (dopt.breakdown::json ->> 'distance_miles')::double precision AS distance,
            rank() OVER (PARTITION BY summ.order_number ORDER BY det.status ASC NULLS FIRST,
                dopt.rank ASC) AS next_vehicle_rank
        FROM
            delivery_summary summ
            JOIN delivery_option dopt ON dopt.order_number = summ.order_number
            LEFT JOIN delivery_detail det ON det.order_number = summ.order_number
                AND det.vehicle_type = dopt.vehicle_type
        WHERE
            summ.status = 'unassigned'
),
timedout_orders AS (
    -- which orders have *all* vehicles timed-out?
    SELECT
        order_number
    FROM
        deliverySnapShot
    GROUP BY
        order_number
    HAVING
        MAX(available_vehicle_rank) = SUM((detail_vehicle_status = 'vehicle_type_timedout')::int)
),
update_summary AS (
    -- mark those orders as timed-out using restaurant-specific or default timeout
    UPDATE
        delivery_summary ds
    SET
        status = 'timedout'
    FROM
        timedout_orders t
    WHERE
        ds.order_number = t.order_number
        AND ds.status = 'unassigned'
        -- Timeout is measured from redispatch_dtts when present (set by
        -- dispatch_cancel_before_pickup on a pre-pickup decline), otherwise
        -- from dtts (order creation). NULL redispatch_dtts preserves the
        -- original behavior for orders that have never been re-dispatched.
        AND (EXTRACT(EPOCH FROM (NOW() - COALESCE(ds.redispatch_dtts, ds.dtts))) / 60) > COALESCE((
            SELECT
                config_value::int
            FROM ordelo_config
            WHERE
                config_key = ds.rest_ref || '_DELIVERY_TIMEOUT_TIME' LIMIT 1), (
            SELECT
                config_value::int
            FROM ordelo_config
            WHERE
                config_key = 'DELIVERY_TIMEOUT_TIME' LIMIT 1), 10 -- fallback to 10 minutes if no config found
)
    RETURNING
        'Order ' || ds.order_number || ' → status set to timeout' AS action
),
to_insert AS (
    -- which un‐assigned orders where all existing details are timed-out
    SELECT
        order_number,
        customer_id,
        available_vehicle_type,
        town,
        rider_payout,
        distance
    FROM
        deliverySnapShot ds_outer
    WHERE
        ds_outer.next_vehicle_rank = 1
        AND ds_outer.detail_vehicle_status IS NULL
        AND NOT EXISTS (
            SELECT
                1
            FROM
                deliverySnapShot ds2
            WHERE
                ds2.order_number = ds_outer.order_number
                AND ds2.detail_vehicle_status IS NOT NULL
                AND ds2.detail_vehicle_status <> 'vehicle_type_timedout')
),
insert_details AS (
    -- insert exactly that “next” vehicle as a new detail row
    INSERT INTO delivery_detail (order_number, customer_id, vehicle_type, town, rider_payout, distance, status)
    SELECT
        order_number,
        customer_id,
        available_vehicle_type,
        town,
        rider_payout,
        distance,
        'unassigned'
    FROM
        to_insert
    RETURNING
        'Order ' || order_number || ' → inserted detail for vehicle_type ' || vehicle_type AS action)
-- finally stitch the two logs together
SELECT
    us.action
FROM
    update_summary us
UNION ALL
SELECT
    id.action
FROM
    insert_details id;
END;
$$;

-- pg_cron job 'process_delivery': runs every 5 seconds, active on live.
-- cron.schedule() with an existing job name updates that job in place, so re-running is safe.
SELECT
    cron.schedule ('process_delivery', '5 seconds', 'SELECT public.process_delivery()');

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.process_delivery () IS 'Advance every unassigned delivery: open the next vehicle-type option or time the order out; returns what it changed.';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- delivery_summary_timedout_whook function
-- select * from process_delivery();
