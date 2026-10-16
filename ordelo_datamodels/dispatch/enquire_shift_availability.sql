-- Function to enquire shift availability by getting active riders and making HTTP POST request
-- Constructs JSON payload from rider data and sends to delivery-hooks endpoint
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

-- pg_cron job 'enquire_shift_availability' (live schedule: 0 11 * * *, active). cron.schedule() updates the job in place when the name already exists.
SELECT
    cron.schedule ('enquire_shift_availability', '0 11 * * *', 'SELECT public.enquire_shift_availability()');

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- select enquire_shift_availability();
