-- =============================================================================================
-- ordelo_datamodels/_orphans/dispatch.sql
-- Unused live functions from earlier versions of the dispatch flow.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16). Orphan candidates: live, no caller found.
-- OBJECTS       fn     complete_dispatch(p_dispatch_id bigint) -> boolean
--                   Earlier completion function (dispatch and detail completed, inflight deleted); dispatch_complete_func() is the one in use.
--               fn     delivery_dispatch_whook() -> trigger
--                   Earlier row-level dispatch webhook to a hard-coded agent.ordelo.app URL; the statement trigger function is the live one.
--               fn     fake_delivery_dispatch_whook(p_rider_ids character varying[]) -> json
--                   Test helper that POSTs a fake dispatch for given riders to /delivery-hooks/delivery-dispatch.
--               fn     handle_delivery_dispatch_changes() -> trigger
--                   Trigger function for an old schema (open/closed statuses, driver_id/cust_id columns that no longer exist); would fail if used.
--               fn     job_assign_delivery() -> void
--                   Earlier version of job_assign_dispatch() (returns void); not scheduled.
--               fn     sync_delivery_inflight() -> trigger
--                   Trigger function that POSTs all delivery_inflight rows to a hard-coded live-track.byteloop.ai URL; no trigger uses it.
--               fn     dispatch_accept_func(p_dispatch_id bigint, p_order_number character varying, p_rider_id character varying) -> json
--                   Older accept function; its only Python caller (agent_app_handlers.process_dispatch_response_from_rider_sync) is never called.
--               fn     notify_missed_dispatches_for_order(p_order_number character varying) -> boolean
--                   Per-order variant of notify_missed_dispatches() posting to a hard-coded agent.ordelo.app URL; never called.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none when applied. Functions that make HTTP calls or change rows only do so if someone calls them.
-- HOW IT FITS   Orphan candidates (Gate 1 decision D1): objects that exist on live but that nothing calls. A search on 2026-10-16 found
--                 no reference in OrdeloAgent, restaurant-frontend or restaurant-agents code, in any other live function or view, in a
--                 trigger or in a pg_cron job. They are captured here exactly as live so the repo describes the whole database.
--                 Nothing has been dropped: deciding keep or drop is an owner decision (docs/to-do.md). Before dropping one, re-check
--                 for callers outside these three repos (other services, manual scripts, Supabase Studio).
-- LIFECYCLE     none
-- CALLED BY     complete_dispatch:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
--               delivery_dispatch_whook:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
--               fake_delivery_dispatch_whook:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
--               handle_delivery_dispatch_changes:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
--               job_assign_delivery:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
--               sync_delivery_inflight:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
--               dispatch_accept_func:
--                 python    ordelo/agent_app_handlers.py: process_dispatch_response_from_rider_sync()
--               notify_missed_dispatches_for_order:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      complete_dispatch(): executable by PUBLIC (default)
--               delivery_dispatch_whook(): executable by PUBLIC (default)
--               fake_delivery_dispatch_whook(): executable by PUBLIC (default)
--               handle_delivery_dispatch_changes(): executable by PUBLIC (default)
--               job_assign_delivery(): executable by PUBLIC (default)
--               sync_delivery_inflight(): executable by PUBLIC (default)
--               dispatch_accept_func(): executable by PUBLIC (default)
--               notify_missed_dispatches_for_order(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       _archive/drop_dispatch_accept_func.sql would drop dispatch_accept_func; it was never run.
--               notify_missed_dispatches_for_order's old repo copy is in _archive/notify_missed_dispatches_tbd.sql.
-- SEE ALSO      docs/to-do.md (decide on orphan candidates)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function complete_dispatch(p_dispatch_id bigint) -> boolean
--   Earlier completion function (dispatch and detail completed, inflight deleted); dispatch_complete_func() is the one in use.
--   Data: writes delivery_detail, delivery_dispatch, delivery_inflight.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.complete_dispatch (p_dispatch_id bigint)
    RETURNS boolean
    LANGUAGE plpgsql
    AS $function$
BEGIN
    -- Update delivery_dispatch status
    UPDATE
        delivery_dispatch
    SET
        status = 'completed'
    WHERE
        dispatch_id = p_dispatch_id;
    -- Update delivery_detail status
    UPDATE
        delivery_detail
    SET
        status = 'completed'
    WHERE
        dispatch_id = p_dispatch_id;
    -- Update delivery_inflight status
    DELETE FROM delivery_inflight
    WHERE dispatch_id = p_dispatch_id;

    RETURN TRUE;
EXCEPTION
    WHEN OTHERS THEN
        RETURN FALSE;
END;

$function$;

-- ---------------------------------------------------------------------------------------------
-- function delivery_dispatch_whook() -> trigger
--   Earlier row-level dispatch webhook to a hard-coded agent.ordelo.app URL; the statement trigger function is the live one.
--   Data: reads delivery_detail.
--   HTTP: POST (HTTP call, URL built at runtime)
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.delivery_dispatch_whook ()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $function$
DECLARE
    response json;
    webhook_payload json;
BEGIN
    -- Combine the NEW record with additional data from a SELECT query
    SELECT
        json_build_object('delivery_dispatch', json_build_array(row_to_json(NEW)), 'delivery_detail', (
                -- Replace this SELECT with your actual query
                SELECT
                    json_agg(row_to_json(t))
                    FROM (
                        SELECT
                            *
                        FROM delivery_detail
                        WHERE
                            order_number = NEW.order_number ORDER BY dtts DESC LIMIT 1) t)) INTO webhook_payload;
    -- Make the HTTP POST request with the combined payload
    response := (
        SELECT
            content
        FROM
            http_post ('https://agent.ordelo.app/delivery-hooks/delivery-dispatch', webhook_payload::text, 'application/json'));
    -- Log the response
    RAISE NOTICE 'Response from HTTP POST: %', response;
    RETURN NEW;
END;
$function$;

-- ---------------------------------------------------------------------------------------------
-- function fake_delivery_dispatch_whook(p_rider_ids character varying[]) -> json
--   Test helper that POSTs a fake dispatch for given riders to /delivery-hooks/delivery-dispatch.
--   Data: reads ordelo_config, rider_master.
--   HTTP: POST /delivery-hooks/delivery-dispatch -> watomation/routers/delivery_hooks.py::delivery_dispatch_hook
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.fake_delivery_dispatch_whook (p_rider_ids character varying[] DEFAULT ARRAY['447448440754' ::character varying, '447448440754' ::character varying])
    RETURNS json
    LANGUAGE plpgsql
    AS $function$
DECLARE
    response json;
    webhook_payload json;
    app_url varchar;
    hook_url varchar;
BEGIN
    PERFORM
        set_config('statement_timeout', '10000', TRUE);

    WITH requested_rider_ids AS (
        SELECT
            rider_id,
            ORDINALITY::int AS row_num
        FROM
            unnest(p_rider_ids)
            WITH ORDINALITY AS r (rider_id, ORDINALITY)
),
rider_rows AS (
SELECT
    requested_rider_ids.row_num,
    rm.rider_id,
    rm.vehicle_type
FROM
    requested_rider_ids
    JOIN rider_master rm ON rm.rider_id = requested_rider_ids.rider_id
    WHERE
        rm.is_in_shift = TRUE
        AND rm.rider_id = ANY (p_rider_ids)
),
new_rows AS (
    SELECT
        123456789 + row_num AS dispatch_id,
        'BNAT-JSLI-27'::varchar AS order_number,
        rider_id,
        6.55::double precision AS rider_payout,
        vehicle_type,
        1.45::double precision AS distance,
        row_num
    FROM
        rider_rows
),
summary_data AS (
    SELECT
        -- current time + 30 mins; timestamptz carries the live UTC offset,
        -- so BST/GMT clock changes need no manual adjustment
        (now() + interval '30 minutes') AS pickup_time,
    '447919202938'::varchar AS rest_id,
    'Burger Nation'::varchar AS rest_name,
    '0.099021'::varchar AS rest_lon,
    '51.375083'::varchar AS rest_lat,
    '261 High St. Orpington BR6 0NW'::varchar AS rest_address,
    'Orpington'::varchar AS town,
    '447428345882'::varchar AS customer_id,
    'Sujith'::varchar AS customer_name,
    '0.0861972'::varchar AS customer_lon,
    '51.360293'::varchar AS customer_lat,
    '16 Ashley Gardens, Orpington BR6 9NH'::varchar AS customer_address
)
SELECT
    json_build_object('bulk_dispatch', COALESCE(json_agg(row_to_json(payload_row)
            ORDER BY src.row_num), '[]'::json)) INTO webhook_payload
FROM (
    SELECT
        rr.row_num,
        nr.dispatch_id,
        nr.order_number,
        nr.rider_id,
        nr.rider_payout,
        nr.vehicle_type,
        nr.distance,
        summ.pickup_time,
        summ.rest_id,
        summ.rest_name,
        summ.rest_lon,
        summ.rest_lat,
        summ.rest_address,
        summ.town,
        summ.customer_id,
        summ.customer_name,
        summ.customer_lon,
        summ.customer_lat,
        summ.customer_address
    FROM
        rider_rows rr
    LEFT JOIN new_rows nr ON nr.row_num = rr.row_num
    LEFT JOIN summary_data summ ON TRUE) src
    CROSS JOIN LATERAL (
        SELECT
            src.dispatch_id,
            src.order_number,
            src.rider_id,
            src.rider_payout,
            src.vehicle_type,
            src.distance,
            src.pickup_time,
            src.rest_id,
            src.rest_name,
            src.rest_lon,
            src.rest_lat,
            src.rest_address,
            src.town,
            src.customer_id,
            src.customer_name,
            src.customer_lon,
            src.customer_lat,
            src.customer_address) payload_row;

    SELECT
        config_value INTO app_url
    FROM
        ordelo_config
    WHERE
        config_key = 'ORDELO_APP_URL';

    IF app_url IS NULL OR length(app_url) = 0 THEN
        app_url := 'https://rider-agent.ordelo.app';
    END IF;

    IF
    RIGHT (app_url,
    1) = '/' THEN
        app_url :=
    LEFT (app_url,
        length(app_url) - 1);
    END IF;
    hook_url := app_url || '/delivery-hooks/delivery-dispatch';

    response := (
        SELECT
            content
        FROM
            http_post (hook_url, webhook_payload::text, 'application/json'));
    RAISE NOTICE 'Payload sent to %: %', hook_url, webhook_payload;
    RAISE NOTICE 'Response from HTTP POST: %', response;

    RETURN response;
END;
$function$;

-- ---------------------------------------------------------------------------------------------
-- function handle_delivery_dispatch_changes() -> trigger
--   Trigger function for an old schema (open/closed statuses, driver_id/cust_id columns that no longer exist); would fail if used.
--   Data: writes delivery_inflight.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.handle_delivery_dispatch_changes ()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $function$
BEGIN
    -- Insert into delivery_inflight when status is 'open'
    IF TG_OP = 'UPDATE' AND NEW.status = 'open' THEN
        INSERT INTO delivery_inflight (dispatch_id, order_number, driver_id, cust_id, dt, ddts)
            VALUES (NEW.dispatch_id, NEW.order_number, NEW.driver_id, NEW.cust_id, NEW.dt, NEW.ddts);
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE'
            AND NEW.status = 'closed' THEN
            DELETE FROM delivery_inflight
            WHERE dispatch_id = OLD.dispatch_id;
        RETURN NEW;
    END IF;
    RETURN NULL;
    -- For other operations, do nothing
END;
$function$;

-- ---------------------------------------------------------------------------------------------
-- function job_assign_delivery() -> void
--   Earlier version of job_assign_dispatch() (returns void); not scheduled.
--   Data: reads delivery_detail; calls assign_accepted_dispatch().
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_assign_delivery ()
    RETURNS void
    LANGUAGE plpgsql
    AS $function$
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
    status = 'unassigned'
        OR status = 'vehicle_type_timedout'
    ORDER BY
        dtts ASC;
    RAISE NOTICE 'Processed unassigned orders.';
ELSE
    RAISE NOTICE 'No unassigned orders found.';
END IF;
END;
$function$;

-- ---------------------------------------------------------------------------------------------
-- function sync_delivery_inflight() -> trigger
--   Trigger function that POSTs all delivery_inflight rows to a hard-coded live-track.byteloop.ai URL; no trigger uses it.
--   Data: reads delivery_inflight.
--   HTTP: POST (HTTP call, URL built at runtime)
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.sync_delivery_inflight ()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $function$
DECLARE
    response json;
    webhook_payload json;
BEGIN
    -- Select all records from delivery_inflight
    SELECT
        json_build_object('delivery_inflight', (
                SELECT
                    json_agg(row_to_json(t))
                FROM (
                    SELECT
                        *
                    FROM delivery_inflight) t)) INTO webhook_payload;
    -- Make the HTTP POST request with the payload
    response := (
        SELECT
            content
        FROM
            http_post ('https://live-track.byteloop.ai/delivery-hooks/delivery-inflight-sync', webhook_payload::text, 'application/json'));
    -- Log the response
    RAISE NOTICE 'Response from HTTP POST: %', response;

    RETURN NEW;
END;
$function$;

-- ---------------------------------------------------------------------------------------------
-- function dispatch_accept_func(p_dispatch_id bigint, p_order_number character varying, p_rider_id character varying) -> json
--   Older accept function; its only Python caller (agent_app_handlers.process_dispatch_response_from_rider_sync) is never called.
--   Data: writes delivery_detail, delivery_dispatch, delivery_inflight.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.dispatch_accept_func (p_dispatch_id bigint, p_order_number character varying, p_rider_id character varying)
    RETURNS json
    LANGUAGE plpgsql
    AS $function$
DECLARE
    result_json json;
BEGIN
    -- Update delivery_dispatch status and status_update_dtts
    UPDATE
        delivery_dispatch
    SET
        status = 'assigned',
        status_update_dtts = CURRENT_TIMESTAMP
    WHERE
        dispatch_id = p_dispatch_id;
    -- Update delivery_detail status, dispatch_id and rider_id
    UPDATE
        delivery_detail
    SET
        status = 'assigned',
        dispatch_id = p_dispatch_id,
        rider_id = p_rider_id
    WHERE
        order_number = p_order_number;
    -- Insert into delivery_inflight
    INSERT INTO delivery_inflight (dispatch_id, order_number, rider_id, customer_id)
        VALUES (p_dispatch_id, p_order_number, p_rider_id, (
                SELECT
                    customer_id
                FROM
                    delivery_detail
                WHERE
                    order_number = p_order_number));
    -- Get the record as JSON
    SELECT
        row_to_json(detail) INTO result_json
    FROM (
        SELECT
            order_number,
            rider_payout,
            distance,
            rest_id,
            rest_name,
            rest_lon,
            rest_lat,
            rest_address,
            town,
            customer_id,
            customer_name,
            customer_lon,
            customer_lat,
            customer_address,
            status,
            dispatch_id,
            rider_id,
            dt,
            dtts
        FROM
            delivery_detail
        WHERE
            delivery_detail.dispatch_id = p_dispatch_id
        LIMIT 1) detail;

    RETURN result_json;
END;
$function$;

-- ---------------------------------------------------------------------------------------------
-- function notify_missed_dispatches_for_order(p_order_number character varying) -> boolean
--   Per-order variant of notify_missed_dispatches() posting to a hard-coded agent.ordelo.app URL; never called.
--   Data: reads delivery_detail, delivery_dispatch.
--   HTTP: POST (HTTP call, URL built at runtime)
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.notify_missed_dispatches_for_order (p_order_number character varying)
    RETURNS boolean
    LANGUAGE plpgsql
    AS $function$
DECLARE
    response json;
    webhook_payload json;
    notified boolean := FALSE;
BEGIN
    WITH missed_dispatches AS (
        SELECT
            dd.order_number,
            json_agg(json_build_object('dispatch_id', d.dispatch_id, 'rider_id', d.rider_id, 'order_number', d.order_number, 'order_status', dd.status, 'dtts', d.dtts)) AS dispatches
        FROM
            delivery_dispatch d
            INNER JOIN delivery_detail dd ON d.order_number = dd.order_number
        WHERE
            d.status = 'accepted'
            AND dd.order_number = p_order_number
            -- AND DATE(d.dtts) = DATE(dd.dtts)
            AND dd.status = 'assigned'
        GROUP BY
            dd.order_number
)
    SELECT
        json_build_object('missed_dispatches', (
                SELECT
                    json_agg(row_to_json(md))
                FROM missed_dispatches md)) INTO webhook_payload;
    -- Make the HTTP POST request with the payload
    response := (
        SELECT
            content
        FROM
            http_post ('https://agent.ordelo.app/delivery-hooks/notify-missed-dispatches', webhook_payload::text, 'application/json'));
    -- Log the response
    RAISE NOTICE 'Response from notify-missed-dispatches: %', response;
    notified := TRUE;
    RETURN notified;
END;
$function$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.complete_dispatch (p_dispatch_id bigint) IS 'Earlier completion function (dispatch and detail completed, inflight deleted); dispatch_complete_func() is the one in use.';

COMMENT ON FUNCTION public.delivery_dispatch_whook () IS 'Earlier row-level dispatch webhook to a hard-coded agent.ordelo.app URL; the statement trigger function is the live one.';

COMMENT ON FUNCTION public.fake_delivery_dispatch_whook (p_rider_ids character varying[]) IS 'Test helper that POSTs a fake dispatch for given riders to /delivery-hooks/delivery-dispatch.';

COMMENT ON FUNCTION public.handle_delivery_dispatch_changes () IS 'Trigger function for an old schema (open/closed statuses, driver_id/cust_id columns that no longer exist); would fail if used.';

COMMENT ON FUNCTION public.job_assign_delivery () IS 'Earlier version of job_assign_dispatch() (returns void); not scheduled.';

COMMENT ON FUNCTION public.sync_delivery_inflight () IS 'Trigger function that POSTs all delivery_inflight rows to a hard-coded live-track.byteloop.ai URL; no trigger uses it.';

COMMENT ON FUNCTION public.dispatch_accept_func (p_dispatch_id bigint, p_order_number character varying, p_rider_id character varying) IS 'Older accept function; its only Python caller (agent_app_handlers.process_dispatch_response_from_rider_sync) is never called.';

COMMENT ON FUNCTION public.notify_missed_dispatches_for_order (p_order_number character varying) IS 'Per-order variant of notify_missed_dispatches() posting to a hard-coded agent.ordelo.app URL; never called.';
