-- =============================================================================================
-- ordelo_datamodels/dispatch/enquire_shift_availability.sql
-- Daily: ask every active rider whether they are working today.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     enquire_shift_availability() -> boolean
--                   POST the active riders to the shift-availability webhook; returns true on success.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each run POSTs to /delivery-hooks/shift-availability-enquiry (which takes every active rider off shift until they answer).
-- HOW IT FITS   cron 'enquire_shift_availability' (11:00 UTC) -> enquire_shift_availability() POSTs all rider_master rows with
--                 status = 'active' to /delivery-hooks/shift-availability-enquiry -> the endpoint sets is_in_shift = false for them and
--                 sends the WhatsApp shift question; a 'yes' sets is_in_shift = true again (watomation/on_callback_wa_handler.py).
-- LIFECYCLE     none
-- CALLED BY     enquire_shift_availability:
--                 cron      'enquire_shift_availability' 0 11 * * *
-- PYTHON MODEL  none
-- SECURITY      enquire_shift_availability(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       11:00 UTC is 12:00 in British Summer Time and 11:00 in winter.
-- SEE ALSO      core/rider_master.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function enquire_shift_availability() -> boolean
--   POST the active riders to the shift-availability webhook; returns true on success.
--   Data: reads ordelo_config, rider_master.
--   HTTP: POST /delivery-hooks/shift-availability-enquiry -> watomation/routers/delivery_hooks.py::shift_availability_enquiry_hook
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION enquire_shift_availability ()
    RETURNS boolean
    AS $$
DECLARE
    app_url text;
    hook_url text;
    webhook_payload jsonb;
    response jsonb;
    riders_data jsonb;
BEGIN
    -- Get active riders data and construct JSON array
    SELECT
        json_agg(json_build_object('rider_id', rider_id, 'rider_name', rider_name))::jsonb INTO riders_data
    FROM ( SELECT DISTINCT
            rider_id,
            rider_name
        FROM
            rider_master
        WHERE
            status = 'active'
        LIMIT 20) active_riders;
    -- Construct the webhook payload
    webhook_payload := json_build_object('event_type', 'shift_availability_enquiry', 'timestamp', extract(epoch FROM now()), 'riders', COALESCE(riders_data, '[]'::jsonb))::jsonb;
    -- Get the app URL from configuration
    SELECT
        config_value INTO app_url
    FROM
        ordelo_config
    WHERE
        config_key = 'ORDELO_APP_URL';

    IF app_url IS NULL OR length(app_url) = 0 THEN
        app_url := 'https://agent.ordelo.app';
    END IF;
    -- Ensure no trailing slash before appending path
    IF
    RIGHT (app_url,
    1) = '/' THEN
        app_url :=
    LEFT (app_url,
        length(app_url) - 1);
    END IF;
    hook_url := app_url || '/delivery-hooks/shift-availability-enquiry';
    -- Make the HTTP POST request
    response := (
        SELECT
            content
        FROM
            http_post (hook_url, webhook_payload::text, 'application/json'));
    -- Return true to indicate successful execution
    RETURN TRUE;

EXCEPTION
    WHEN OTHERS THEN
        -- Log error and return false
        RAISE NOTICE 'Error in enquire_shift_availability: %', SQLERRM;
        RETURN FALSE;
END;

$$
LANGUAGE plpgsql;

-- pg_cron job 'enquire_shift_availability': runs every 0 11 * * *, active on live.
-- cron.schedule() with an existing job name updates that job in place, so re-running is safe.
SELECT
    cron.schedule ('enquire_shift_availability', '0 11 * * *', 'SELECT public.enquire_shift_availability()');

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.enquire_shift_availability () IS 'POST the active riders to the shift-availability webhook; returns true on success.';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- select enquire_shift_availability();
