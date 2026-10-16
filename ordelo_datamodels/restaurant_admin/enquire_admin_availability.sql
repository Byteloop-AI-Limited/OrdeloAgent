-- =============================================================================================
-- ordelo_datamodels/restaurant_admin/enquire_admin_availability.sql
-- Daily: ask each restaurant's admins whether they are open for orders today.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     enquire_admin_availability(p_rest_ref_list character varying[]) -> boolean
--                   POST the admins of the given restaurants (all when NULL) to the admin-availability webhook; returns true on success.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each run POSTs the restaurants' admin phones to /delivery-hooks/admin-availability-enquiry (WhatsApp question to admins).
-- HOW IT FITS   Restaurant confirmation, delivery and takeaway alike:
--                 new order -> init_delivery() / init_takeaway() -> resolve_initial_restaurant_acceptance():
--                     auto_accept restaurants: order starts accepted with a default pickup time (no prompt)
--                     otherwise: 'restaurant_unconfirmed' -> trigger -> admins prompted (WhatsApp buttons; Telegram order cards)
--                 admin taps Accept / Decline -> restaurant_order_decide(); picks a pickup time -> restaurant_order_set_pickup()
--                     (Telegram taps go through t_order_decide() / t_order_set_pickup(), which authorise the person first)
--                 no answer -> process_restaurant_confirmation() (cron 10 s) -> 'restaurant_timedout' -> trigger -> Python sets a default
--                     pickup time and makes the order dispatchable (delivery_hooks._handle_restaurant_timedout)
--                 morning check -> enquire_admin_availability() (cron 11:00 UTC) asks admins whether the restaurant is open today.
--                 cron 'enquire_admin_availability' runs it for ARRAY['ELAS','SFCS','BNAT'] (hard-coded in the cron command).
-- LIFECYCLE     none
-- CALLED BY     enquire_admin_availability:
--                 cron      'enquire_admin_availability' 0 11 * * *
--                 python    utils_common/waba_utils/wa_senders.py (module-level SQL)
-- PYTHON MODEL  none
-- SECURITY      enquire_admin_availability(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       New restaurants are not asked until the cron command's restaurant list is edited.
-- SEE ALSO      core/restaurant_master.sql (admins)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function enquire_admin_availability(p_rest_ref_list character varying[]) -> boolean
--   POST the admins of the given restaurants (all when NULL) to the admin-availability webhook; returns true on success.
--   Data: reads ordelo_config, restaurant_master.
--   HTTP: POST /delivery-hooks/admin-availability-enquiry -> watomation/routers/delivery_hooks.py::admin_availability_enquiry_hook
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION enquire_admin_availability (p_rest_ref_list varchar[] DEFAULT NULL)
    RETURNS boolean
    AS $$
DECLARE
    app_url text;
    hook_url text;
    webhook_payload jsonb;
    response jsonb;
    admins_data jsonb;
BEGIN
    -- Get restaurant admins data and construct JSON object {rest_ref: [admins], ...}
    IF p_rest_ref_list IS NULL THEN
        -- Get all active restaurants with admins
        SELECT
            json_object_agg(rest_ref, admins)::jsonb INTO admins_data
        FROM (
            SELECT
                rest_ref,
                admins
            FROM
                restaurant_master
            WHERE
                admins IS NOT NULL
                AND array_length(admins, 1) > 0) restaurant_admins;
    ELSE
        -- Get only specified restaurants with admins
        SELECT
            json_object_agg(rest_ref, admins)::jsonb INTO admins_data
        FROM (
            SELECT
                rest_ref,
                admins
            FROM
                restaurant_master
            WHERE
                rest_ref = ANY (p_rest_ref_list)
                AND admins IS NOT NULL
                AND array_length(admins, 1) > 0) restaurant_admins;
    END IF;
    -- Construct the webhook payload
    webhook_payload := json_build_object('event_type', 'admin_availability_enquiry', 'timestamp', extract(epoch FROM now()), 'restaurant_admins', COALESCE(admins_data, '{}'::jsonb))::jsonb;
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
    hook_url := app_url || '/delivery-hooks/admin-availability-enquiry';
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
        RAISE NOTICE 'Error in enquire_admin_availability: %', SQLERRM;
        RETURN FALSE;
END;

$$
LANGUAGE plpgsql;

-- pg_cron job 'enquire_admin_availability': runs every 0 11 * * *, active on live.
-- cron.schedule() with an existing job name updates that job in place, so re-running is safe.
SELECT
    cron.schedule ('enquire_admin_availability', '0 11 * * *', 'select enquire_admin_availability(ARRAY[''ELAS'', ''SFCS'', ''BNAT'']);');

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.enquire_admin_availability (p_rest_ref_list character varying[]) IS 'POST the admins of the given restaurants (all when NULL) to the admin-availability webhook; returns true on success.';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- Example usage:
-- select enquire_admin_availability(); -- All restaurants
-- select enquire_admin_availability(ARRAY['ELAS']); -- Specific restaurants

-- select enquire_admin_availability(ARRAY['BNAT']); -- Specific restaurants
