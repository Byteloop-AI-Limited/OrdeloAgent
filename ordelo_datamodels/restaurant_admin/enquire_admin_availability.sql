-- Function to enquire admin availability by getting restaurant admins and making HTTP POST request
-- Constructs JSON payload from restaurant admin data and sends to delivery-hooks endpoint
-- Takes optional p_rest_ref_list parameter to filter specific restaurants
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

-- pg_cron job 'enquire_admin_availability' (live schedule: 0 11 * * *, active). cron.schedule() updates the job in place when the name already exists.
SELECT
    cron.schedule ('enquire_admin_availability', '0 11 * * *', 'select enquire_admin_availability(ARRAY[''ELAS'', ''SFCS'', ''BNAT'']);');

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- Example usage:
-- select enquire_admin_availability(); -- All restaurants
-- select enquire_admin_availability(ARRAY['ELAS']); -- Specific restaurants

-- select enquire_admin_availability(ARRAY['BNAT']); -- Specific restaurants
