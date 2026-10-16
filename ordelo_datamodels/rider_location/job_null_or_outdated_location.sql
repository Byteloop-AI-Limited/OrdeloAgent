-- =============================================================================================
-- ordelo_datamodels/rider_location/job_null_or_outdated_location.sql
-- Alert about live deliveries whose rider has no recent GPS fix (job currently INACTIVE).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     job_null_or_outdated_location() -> boolean
--                   POST live jobs whose rider location is missing or stale to the null-or-outdated-location hook; returns whether it posted.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  When scheduled, each run may POST to /location-hooks/null-or-outdated-location.
-- HOW IT FITS   Continuous rider tracking (OwnTracks app on the rider's phone):
--                 OwnTracks -> HTTP endpoint -> pgmq queue 'owntracks' (schema pgmq)
--                 cron 'job_process_owntracks' (30 s) -> job_process_owntracks():
--                     location messages  -> rider_location (one row per GPS fix, linked to the rider's live order if any)
--                     transition events  -> rider_location_event (enter / leave a region)
--                                           -> trigger -> POST /location-hooks/notify-rider-location-event (customer / restaurant updates)
--                 The customer's live map (/location-hooks/live-location-map/{order}) reads rider_location.
--                 job_null_or_outdated_location() (cron, INACTIVE) would alert about live jobs whose rider sent no recent fix.
--                 Looks at delivery_inflight jobs whose rider's latest rider_location is missing or older than
--                 ordelo_config LOCATION_ENABLE_TIME_INTERVAL minutes (default 1) and POSTs them to
--                 /location-hooks/null-or-outdated-location, which asks the rider to switch location sharing on.
-- LIFECYCLE     none
-- CALLED BY     job_null_or_outdated_location:
--                 cron      'job_null_or_outdated_location' * * * * * (INACTIVE)
-- PYTHON MODEL  none
-- SECURITY      job_null_or_outdated_location(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       The cron job exists but is inactive on live; the on-demand WhatsApp location flow (rider_location/wa_location.sql) is the
--                 current way to get a rider's position.
--               The body was taken from live on 2026-10-16: the previous repo copy differed.
-- SEE ALSO      rider_location/wa_location.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function job_null_or_outdated_location() -> boolean
--   POST live jobs whose rider location is missing or stale to the null-or-outdated-location hook; returns whether it posted.
--   Data: reads delivery_inflight, ordelo_config, rider_location.
--   HTTP: POST /location-hooks/null-or-outdated-location -> watomation/routers/location_hooks.py::notify_rider_null_or_outdated_location
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_null_or_outdated_location ()
    RETURNS boolean
    LANGUAGE plpgsql
    AS $function$
DECLARE
    interval_minutes int;
    interval_expr interval;
    webhook_payload json;
    response json;
    notified boolean := FALSE;
    ordelo_app_url text;
    webhook_url text;
BEGIN
    -- Get the interval in minutes from config
    SELECT
        config_value::int INTO interval_minutes
    FROM
        ordelo_config
    WHERE
        config_key = 'LOCATION_ENABLE_TIME_INTERVAL';
    IF interval_minutes IS NULL THEN
        interval_minutes := 1;
        -- Default fallback
    END IF;
    interval_expr := (interval_minutes || ' minutes')::interval;
    -- Get the base app URL from config
    SELECT
        config_value INTO ordelo_app_url
    FROM
        ordelo_config
    WHERE
        config_key = 'ORDELO_APP_URL';
    IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
        ordelo_app_url := 'https://rider-agent.ordelo.app';
        -- Fallback default
    END IF;
    webhook_url := ordelo_app_url || '/location-hooks/null-or-outdated-location';

    WITH inflight_missing_location AS (
        SELECT
            inflight.order_number,
            inflight.rider_id,
            MAX(location.dtts) AS last_location_dtts
        FROM
            delivery_inflight inflight
        LEFT JOIN rider_location location ON inflight.order_number = location.order_number
            AND inflight.rider_id = location.rider_id
    GROUP BY
        inflight.order_number,
        inflight.rider_id
),
inflight_to_notify AS (
    SELECT
        order_number,
        rider_id,
        last_location_dtts AS dtts,
        CASE WHEN last_location_dtts IS NULL THEN
            'NO_LOCATION_DATA'
        ELSE
            'OUTDATED_LOCATION_DATA'
        END AS reason
    FROM
        inflight_missing_location
    WHERE
        last_location_dtts IS NULL
        OR (CURRENT_TIMESTAMP - last_location_dtts) > interval_expr
)
SELECT
    json_agg(json_build_object('order_number', order_number, 'rider_id', rider_id, 'reason', reason, 'dtts', dtts)) INTO webhook_payload
FROM
    inflight_to_notify;
    -- Only POST if there is at least one item
    IF webhook_payload IS NOT NULL THEN
        response := (
            SELECT
                content
            FROM
                http_post (webhook_url, webhook_payload::text, 'application/json'));
        RAISE NOTICE 'Response from null-or-outdated-location: %', response;
        notified := TRUE;
    ELSE
        RAISE NOTICE 'No inflight deliveries missing location data.';
        notified := FALSE;
    END IF;
    RETURN notified;
END;
$function$;

-- pg_cron job 'job_null_or_outdated_location': runs every * * * * *, INACTIVE (re-disabled by the next statement) on live.
-- cron.schedule() with an existing job name updates that job in place, so re-running is safe.
SELECT
    cron.schedule ('job_null_or_outdated_location', '* * * * *', 'SELECT public.job_null_or_outdated_location()');

SELECT
    cron.alter_job (jobid, active := FALSE)
FROM
    cron.job
WHERE
    jobname = 'job_null_or_outdated_location';

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.job_null_or_outdated_location () IS 'POST live jobs whose rider location is missing or stale to the null-or-outdated-location hook; returns whether it posted.';

-- Usage:
-- select job_null_or_outdated_location();
