-- =============================================================================================
-- ordelo_datamodels/rider_location/job_process_owntracks.sql
-- Every 30 seconds: move OwnTracks messages from the pgmq queue into rider_location and rider_location_event.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     job_process_owntracks() -> integer
--                   Drain the 'owntracks' pgmq queue into rider_location / rider_location_event; returns how many messages it processed.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each run reads up to 1000 messages from pgmq queue 'owntracks', inserts location/event rows and archives the messages.
-- HOW IT FITS   Continuous rider tracking (OwnTracks app on the rider's phone):
--                 OwnTracks -> HTTP endpoint -> pgmq queue 'owntracks' (schema pgmq)
--                 cron 'job_process_owntracks' (30 s) -> job_process_owntracks():
--                     location messages  -> rider_location (one row per GPS fix, linked to the rider's live order if any)
--                     transition events  -> rider_location_event (enter / leave a region)
--                                           -> trigger -> POST /location-hooks/notify-rider-location-event (customer / restaurant updates)
--                 The customer's live map (/location-hooks/live-location-map/{order}) reads rider_location.
--                 job_null_or_outdated_location() (cron, INACTIVE) would alert about live jobs whose rider sent no recent fix.
-- LIFECYCLE     none
-- CALLED BY     job_process_owntracks:
--                 cron      'job_process_owntracks' 30 seconds
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/watomation/routers/rider_event_hooks.py
-- PYTHON MODEL  none
-- SECURITY      job_process_owntracks(): executable by PUBLIC (default); SECURITY DEFINER
-- TESTS         none
-- GOTCHAS       SECURITY DEFINER with default grants: any API role can run it (docs/to-do.md).
--               Needs the pgmq extension and the 'owntracks' queue (pgmq.q_owntracks / pgmq.a_owntracks).
-- SEE ALSO      rider_location/rider_location.sql
--               rider_location/rider_location_event.sql
--               docs/location_overview.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function job_process_owntracks() -> integer
--   Drain the 'owntracks' pgmq queue into rider_location / rider_location_event; returns how many messages it processed.
--   Data: reads delivery_inflight; writes rider_location, rider_location_event.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_process_owntracks ()
    RETURNS int
    LANGUAGE plpgsql
    SECURITY DEFINER
    AS $$
DECLARE
    rec_loop RECORD;
    msg_ids bigint[];
    v_msg_id bigint;
    v_processed_count int := 0;
BEGIN
    WITH msgs AS (
        SELECT
            msg_id,
            message::jsonb AS msg
        FROM
            pgmq.read ('owntracks', 0, 1000)
),
parsed AS (
    SELECT
        msg ->> '_type' AS _type,
        msg ->> 'topic' AS topic,
        (regexp_match(msg ->> 'topic', 'owntracks/([^/]+)/'))[1] AS rider_id,
        (msg ->> 'tst')::bigint AS tst,
        to_timestamp((msg ->> 'tst')::bigint) AS tst_dtts,
        msg
    FROM
        msgs
),
location_rows AS (
    SELECT
        topic,
        p.rider_id,
        inflight.customer_id,
        inflight.order_number,
        (msg ->> 'acc')::int AS acc,
        (msg ->> 'alt')::int AS alt,
        (msg ->> 'batt')::int AS batt,
        (msg ->> 'lat')::float AS lat,
        (msg ->> 'lon')::float AS lon,
        (msg ->> 'tst')::int AS tst,
        msg ->> 'tid' AS tid,
        msg ->> 'conn' AS conn,
        (
            SELECT
                array_agg(val)
            FROM
                jsonb_array_elements_text(msg -> 'inregions') AS elem (val)) AS inregions,
        (
            SELECT
                array_agg(val)
            FROM
                jsonb_array_elements_text(msg -> 'inrids') AS elem (val)) AS inrids,
            (msg ->> 'created_at')::int AS created_at,
            (msg -> 'm')::int AS m,
            tst_dtts
        FROM
            parsed p
            JOIN delivery_inflight inflight ON inflight.rider_id = p.rider_id
        WHERE
            p._type = 'location'
),
transition_rows AS (
    SELECT
        topic,
        p.rider_id,
        inflight.customer_id,
        inflight.order_number,
        msg ->> 'rid' AS rid,
        msg ->> 'event' AS event
    FROM
        parsed p
        JOIN delivery_inflight inflight ON inflight.rider_id = p.rider_id
    WHERE
        p._type = 'transition'
),
loc_insert AS (
    -- Use a single WITH statement for both inserts to maintain CTE scope
    INSERT INTO rider_location
    SELECT
        *
    FROM
        location_rows
    RETURNING
        1
),
event_insert AS (
INSERT INTO rider_location_event (topic, rider_id, customer_id, order_number, rid, event)
    SELECT
        *
    FROM
        transition_rows
    RETURNING
        1
),
msg_id_collect AS (
    SELECT
        array_agg(msg_id) AS ids
FROM
    msgs
)
SELECT
    ids INTO msg_ids
FROM
    msg_id_collect;
    -- Archive processed messages
    IF msg_ids IS NOT NULL THEN
        v_processed_count := array_length(msg_ids, 1);
        FOREACH v_msg_id IN ARRAY msg_ids LOOP
            PERFORM
                pgmq.archive ('owntracks', v_msg_id);
        END LOOP;
    END IF;

    RETURN v_processed_count;
END;
$$;

-- pg_cron job 'job_process_owntracks': runs every 30 seconds, active on live.
-- cron.schedule() with an existing job name updates that job in place, so re-running is safe.
SELECT
    cron.schedule ('job_process_owntracks', '30 seconds', 'SELECT public.job_process_owntracks()');

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.job_process_owntracks () IS 'Drain the ''owntracks'' pgmq queue into rider_location / rider_location_event; returns how many messages it processed.';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- / *
-- """
-- Processes OwnTracks messages from a queue into location tables.
--   . Reads messages from pgmq queue 'owntracks'
--   . Processes location data into rider_location table
--   . Processes transition events into rider_location_event table (always inserts new records, no upsert)
--   . Archives processed messages
--   . Returns the count of processed messages
-- Functions:
--   . job_process_owntracks
-- """
-- */;
