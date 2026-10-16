-- =============================================================================================
-- ordelo_datamodels/rider_location/rider_location_event.sql
-- Rider region enter/leave events from OwnTracks, each forwarded to OrdeloAgent by a trigger.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  rider_location_event
--                   One OwnTracks transition: rider, region id (rid), event enter|leave, linked order/customer when known.
--               fn     rider_location_event_update() -> trigger
--                   Row trigger function: POST the new event to /location-hooks/notify-rider-location-event.
--               trg    trigger_rider_location_event_update on rider_location_event -> rider_location_event_update()
--                   AFTER INSERT ON rider_location_event FOR EACH ROW.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Applying the file re-creates the trigger; each INSERT POSTs to /location-hooks/notify-rider-location-event.
-- HOW IT FITS   Continuous rider tracking (OwnTracks app on the rider's phone):
--                 OwnTracks -> HTTP endpoint -> pgmq queue 'owntracks' (schema pgmq)
--                 cron 'job_process_owntracks' (30 s) -> job_process_owntracks():
--                     location messages  -> rider_location (one row per GPS fix, linked to the rider's live order if any)
--                     transition events  -> rider_location_event (enter / leave a region)
--                                           -> trigger -> POST /location-hooks/notify-rider-location-event (customer / restaurant updates)
--                 The customer's live map (/location-hooks/live-location-map/{order}) reads rider_location.
--                 job_null_or_outdated_location() (cron, INACTIVE) would alert about live jobs whose rider sent no recent fix.
-- LIFECYCLE     append-only.
-- CALLED BY     rider_location_event:
--                 sql       job_process_owntracks()
--                 python    watomation/on_message_wa_handler.py: test_delivery()
--                 python    watomation/routers/location_hooks.py: process_location_transitionTBD()
--                 r-agents  restaurant-agents/packages/restaurant-agent-runtime/src/restaurant_agent_runtime/watomation/routers/rider_event_hooks.py
--               rider_location_event_update:
--                 trigger   trigger_rider_location_event_update on rider_location_event
-- PYTHON MODEL  none
-- SECURITY      rider_location_event: RLS OFF; Supabase default grants (anon and authenticated can read and write)
--               rider_location_event_update(): executable by PUBLIC (default)
-- TESTS         tests/watomation/routers/test_location_hooks.py
-- GOTCHAS       none
-- SEE ALSO      rider_location/job_process_owntracks.sql
--               docs/location_overview.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table rider_location_event
--   One OwnTracks transition: rider, region id (rid), event enter|leave, linked order/customer when known.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.rider_location_event (
    id serial NOT NULL,
    topic character varying(255),
    rider_id character varying(12) NOT NULL,
    customer_id character varying(12),
    order_number character varying(100),
    rid character varying(20) NOT NULL,
    event character varying(20) NOT NULL,
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT rider_location_event_pkey PRIMARY KEY (id)
);

-- ---------------------------------------------------------------------------------------------
-- function rider_location_event_update() -> trigger
--   Row trigger function: POST the new event to /location-hooks/notify-rider-location-event.
--   Data: reads ordelo_config.
--   HTTP: POST /location-hooks/notify-rider-location-event -> watomation/routers/location_hooks.py::notify_rider_location_event
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rider_location_event_update ()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
DECLARE
    webhook_payload json;
    app_url varchar;
    hook_url varchar;
BEGIN
    -- Build the webhook payload as just the inserted record
    webhook_payload := row_to_json(NEW);
    -- Fetch app_url from config
    SELECT
        config_value INTO app_url
    FROM
        ordelo_config
    WHERE
        config_key = 'ORDELO_APP_URL';

    IF app_url IS NULL OR length(app_url) = 0 THEN
        app_url := 'https://rider-agent.ordelo.app';
    END IF;
    -- Ensure no trailing slash before appending path
    IF
    RIGHT (app_url,
    1) = '/' THEN
        app_url :=
    LEFT (app_url,
        length(app_url) - 1);
    END IF;
    hook_url := app_url || '/location-hooks/notify-rider-location-event';
    -- Make the HTTP POST request and ignore the response
    PERFORM
        http_post (hook_url, webhook_payload::text, 'application/json');
    RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- trigger trigger_rider_location_event_update on rider_location_event -> rider_location_event_update()
--   AFTER INSERT ON rider_location_event FOR EACH ROW.
-- ---------------------------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trigger_rider_location_event_update ON public.rider_location_event;

CREATE TRIGGER trigger_rider_location_event_update
    AFTER INSERT ON rider_location_event
    FOR EACH ROW
    EXECUTE FUNCTION rider_location_event_update ();

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.rider_location_event IS 'One OwnTracks transition: rider, region id (rid), event enter|leave, linked order/customer when known.';

COMMENT ON FUNCTION public.rider_location_event_update () IS 'Row trigger function: POST the new event to /location-hooks/notify-rider-location-event.';

COMMENT ON TRIGGER trigger_rider_location_event_update ON public.rider_location_event IS 'AFTER INSERT ON rider_location_event FOR EACH ROW.';
