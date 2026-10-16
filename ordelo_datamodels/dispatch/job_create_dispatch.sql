/**
Dispatch Creation and Management – Step 3 in Delivery Workflow

Where This Fits in the Journey:
    - This function is the third step in the delivery agent workflow, as outlined in handwritten_design.md.
    - Step 1: init_delivery – Creates delivery_summary and calls process_delivery().
    - Step 2: process_delivery – Creates delivery_detail records and manages assignment/timeouts.
    - Step 3: job_create_dispatch – For each unassigned order/vehicle type, finds available riders, inserts records into delivery_dispatch, and updates statuses for next batch or vehicle type.
    - Step 4+: Downstream jobs and triggers handle dispatch assignment, inflight tracking, and notifications.

Invocation:
    - Scheduled cron job 'job_create_dispatch' (typically every 5 seconds).
    - Operates on all unassigned delivery_detail records.

Purpose:
    - Create new dispatch entries based on available riders (via get_available_riders()).
    - TEST3100 orders are restricted to normally eligible overwatch riders.
    - Prioritize rider selection by priority during dispatch creation.
    - Update delivery_detail with `vehicle_type_timedout` when no more available riders exist for dispatch.
    - Control batch size of dispatches using config value `DISPATCH_BATCH_SIZE_` per vehicle type.

Dependencies:
    - Reads from: `delivery_detail`, `ordelo_config` (for batch size), and result of get_available_riders().
    - Writes to: `delivery_dispatch`, `delivery_detail` (status updates).

Side Effects:
    1. Triggers webhook: /delivery-hooks/delivery-dispatch on insert into `delivery_dispatch`.
    2. Sends WhatsApp messages to riders with delivery summaries.
    3. Enables subsequent assignment and inflight jobs.

See also: jobs_n_functions/handwritten_design.md for the full delivery journey.
**/
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
        LOWER(allRiders.town) = LOWER(p_town)
        AND allRiders.vehicle_type = p_vehicle_type
        AND allRiders.is_in_shift
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

-- pg_cron job 'job_create_dispatch' (live schedule: 5 seconds, active). cron.schedule() updates the job in place when the name already exists.
SELECT
    cron.schedule ('job_create_dispatch', '5 seconds', 'SELECT public.job_create_dispatch()');
