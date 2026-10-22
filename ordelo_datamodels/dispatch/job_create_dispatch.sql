-- =============================================================================================
-- ordelo_datamodels/dispatch/job_create_dispatch.sql
-- Every 5 seconds: offer open delivery options to available riders (insert delivery_dispatch rows), in batches.
-- =============================================================================================
-- LIVE CHECK    TARGET SHAPE (phase R1 of plans/telegram-rider-bot-plan.md): job_create_dispatch() matches live (2026-10-16);
--                 get_available_riders() here adds status = 'active' and NOT is_paused(...), which are NOT yet live. The owner
--                 applies availability/pauses.sql, then this file (see migrations/rider_telegram_r1.sql for the order).
-- OBJECTS       fn     job_create_dispatch() -> TABLE(action text)
--                   Create the next batch of offers for every open delivery option, or time the vehicle type out; returns what it did.
--               fn     get_available_riders(p_order_number text, p_town text, p_vehicle_type text) -> TABLE(rider_id character varying, priority integer)
--                   Return the riders (rider_id, priority) who may be offered this order for this town and vehicle type.
-- REQUIRES      core/rider_master.sql
--               availability/pauses.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each run inserts delivery_dispatch rows (one webhook per run via the statement trigger) and may mark
--               delivery_detail 'vehicle_type_timedout'.
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
-- LIFECYCLE     For each delivery_detail in 'unassigned' (only when no offer for that order/vehicle is still 'unassigned'):
--                 get_available_riders() -> rank by rider_master.priority -> insert the next DISPATCH_BATCH_SIZE_<VEHICLE> offers.
--                 When no rider is left for that vehicle type -> delivery_detail.status = 'vehicle_type_timedout'
--                 (process_delivery() then opens the next vehicle type or times the order out).
-- CALLED BY     job_create_dispatch:
--                 cron      'job_create_dispatch' 5 seconds
--               get_available_riders:
--                 sql       job_create_dispatch() (dispatch/job_create_dispatch.sql)
-- PYTHON MODEL  none
-- SECURITY      job_create_dispatch(): executable by PUBLIC (default)
--               get_available_riders(): executable by PUBLIC (default)
-- TESTS         tests/sql/test_rider_onboarding_sql.py (get_available_riders: status gate and pauses)
-- GOTCHAS       TEST3100 orders (order_has_test_item) are offered only to riders listed in ordelo_config overwatch_list.
--               Only rider_master.status = 'active' (exact, case-sensitive) is dispatchable (D41): Telegram sign-ups start
--                 'inactive'. A rider with an open pause (availability/pauses.sql) is skipped until its end time (D51).
--               A rider is never offered the same order twice, and riders on another job (delivery_inflight) are skipped.
-- SEE ALSO      dispatch/delivery_dispatch.sql
--               core/rider_master.sql
--               availability/pauses.sql
--               ordering/order_has_test_item.sql
--               docs/dispatch_flow.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function job_create_dispatch() -> TABLE(action text)
--   Create the next batch of offers for every open delivery option, or time the vehicle type out; returns what it did.
--   Data: reads ordelo_config; writes delivery_detail, delivery_dispatch; calls get_available_riders().
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION job_create_dispatch ()
    RETURNS TABLE (
        action text
    )
    AS $$
DECLARE
    has_unassigned boolean;
BEGIN
    SELECT
        EXISTS (
            SELECT
                1
            FROM
                delivery_detail
            WHERE
                status = 'unassigned'
            LIMIT 1) INTO has_unassigned;
    IF has_unassigned THEN
        RETURN QUERY WITH availableRiders AS (
            SELECT
                dd.order_number,
                gar.rider_id AS rider_id_to_dispatch,
                gar.priority,
                dd.rider_payout,
                dd.distance,
                dd.vehicle_type,
                COUNT(gar.rider_id) AS rider_count
            FROM
                delivery_detail dd
            LEFT JOIN LATERAL get_available_riders (dd.order_number, LOWER(dd.town), dd.vehicle_type) gar ON TRUE
        WHERE
            dd.status = 'unassigned'
        GROUP BY
            dd.order_number,
            dd.rider_payout,
            dd.distance,
            dd.vehicle_type,
            gar.rider_id,
            gar.priority
),
dispatch_candidates AS (
    SELECT
        ar.order_number,
        ar.rider_id_to_dispatch,
        ar.rider_payout,
        ar.distance,
        ar.vehicle_type,
        ar.rider_count,
        COALESCE(oc.config_value::int, 1) AS batch_size,
        row_number() OVER (PARTITION BY ar.order_number,
            ar.vehicle_type ORDER BY ar.priority ASC) AS rn
    FROM
        availableRiders ar
        LEFT JOIN ordelo_config oc ON oc.config_key = 'DISPATCH_BATCH_SIZE_' || UPPER(ar.vehicle_type)
),
dispatch_insert AS (
INSERT INTO delivery_dispatch (order_number, rider_id, rider_payout, distance, vehicle_type, status)
    SELECT
        order_number,
        rider_id_to_dispatch,
        rider_payout,
        distance,
        vehicle_type,
        'unassigned'
    FROM
        dispatch_candidates
    WHERE
        rider_count > 0
        AND rn <= batch_size
    RETURNING
        'Order ' || order_number || 'vehicle_type ' || vehicle_type || ' → dispatch created for rider ' || rider_id AS action,
        order_number
),
update_detail_logs AS (
    UPDATE
        delivery_detail dd
    SET
        status = 'vehicle_type_timedout'
    FROM
        availableRiders ar
    WHERE
        dd.order_number = ar.order_number
        AND dd.vehicle_type = ar.vehicle_type
        AND dd.status = 'unassigned'
        AND dd.order_number NOT IN (
            SELECT
                di.order_number
            FROM
                dispatch_insert di)
        RETURNING
            'Order ' || dd.order_number || ' vehicle_type ' || dd.vehicle_type || ' → status set to vehicle_type_timedout' AS action
)
SELECT
    di.action
FROM
    dispatch_insert di
UNION ALL
SELECT
    ul.action
FROM
    update_detail_logs ul;
ELSE
    RETURN QUERY
    SELECT
        'No unassigned orders found.'::text AS action;
END IF;
END;
$$
LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------
-- function get_available_riders(p_order_number text, p_town text, p_vehicle_type text) -> TABLE(rider_id character varying, priority integer)
--   Return the riders (rider_id, priority) who may be offered this order for this town and vehicle type.
--   status = 'active', same town (case-insensitive) and vehicle, is_in_shift, not paused, not offered this order before,
--   not on another job; TEST3100 orders only to overwatch_list riders.
--   Data: reads delivery_dispatch, delivery_inflight, ordelo_config, rider_master; calls order_has_test_item(), is_paused().
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION get_available_riders (p_order_number text, p_town text, p_vehicle_type text)
    RETURNS TABLE (
        rider_id varchar(12),
        priority int
    )
    AS $$
BEGIN
    RETURN QUERY WITH ridersToExclude AS (
        SELECT DISTINCT
            dDispatch.rider_id,
            dDispatch.vehicle_type
        FROM
            delivery_dispatch dDispatch
        WHERE
            dDispatch.order_number = p_order_number
        UNION
        SELECT DISTINCT
            inflight.rider_id,
            'inflight'
        FROM
            delivery_inflight inflight
)
    SELECT
        allRiders.rider_id,
        allRiders.priority
    FROM
        rider_master allRiders
    WHERE
        allRiders.status = 'active'
        AND LOWER(allRiders.town) = LOWER(p_town)
        AND allRiders.vehicle_type = p_vehicle_type
        AND allRiders.is_in_shift
        AND NOT public.is_paused ('rider', allRiders.rider_id, NULL)
        -- Restrict before priority/batch ranking. Unknown orders have no candidates.
        AND CASE public.order_has_test_item (p_order_number)
        WHEN FALSE THEN
            TRUE
        WHEN TRUE THEN
            EXISTS (
                SELECT
                    1
                FROM
                    ordelo_config oc,
                    LATERAL regexp_split_to_table(COALESCE(oc.config_value, ''), ',') AS member (number)
                WHERE
                    oc.config_key = 'overwatch_list'
                    AND btrim(member.number) = allRiders.rider_id)
        ELSE
            FALSE
    END
        AND NOT EXISTS (
            SELECT
                1
            FROM
                ridersToExclude
            WHERE
                ridersToExclude.rider_id = allRiders.rider_id);

END;
$$
LANGUAGE plpgsql;

-- pg_cron job 'job_create_dispatch': runs every 5 seconds, active on live.
-- cron.schedule() with an existing job name updates that job in place, so re-running is safe.
SELECT
    cron.schedule ('job_create_dispatch', '5 seconds', 'SELECT public.job_create_dispatch()');

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.job_create_dispatch () IS 'Create the next batch of offers for every open delivery option, or time the vehicle type out; returns what it did.';

COMMENT ON FUNCTION public.get_available_riders (p_order_number text, p_town text, p_vehicle_type text) IS 'Return the riders (rider_id, priority) who may be offered this order for this town and vehicle type.';
