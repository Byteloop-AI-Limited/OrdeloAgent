-- =============================================================================================
-- ordelo_datamodels/dispatch/notify_missed_dispatches.sql
-- Tell the riders who accepted an order but lost it to another rider (called when the order is assigned).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     notify_missed_dispatches() -> boolean
--                   POST every accepted-but-lost dispatch (all orders) to /delivery-hooks/notify-missed-dispatches; returns true once posted.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call may POST to /delivery-hooks/notify-missed-dispatches.
-- HOW IT FITS   delivery_inflight_whook() calls it right after an order is assigned. It collects, across all orders, dispatches still
--                 'accepted' whose delivery_detail is already 'assigned' (riders who tapped Accept but lost the order) and POSTs them,
--                 grouped by order, to /delivery-hooks/notify-missed-dispatches; the endpoint (delivery_hooks.notify_missed_dispatches_hook)
--                 tells those riders and marks their dispatches 'missed'.
-- LIFECYCLE     none
-- CALLED BY     notify_missed_dispatches:
--                 sql       delivery_inflight_whook() (dispatch/delivery_inflight.sql)
-- PYTHON MODEL  none
-- SECURITY      notify_missed_dispatches(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       none
-- SEE ALSO      dispatch/delivery_inflight.sql
--               _orphans/dispatch.sql (notify_missed_dispatches_for_order, unused)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function notify_missed_dispatches() -> boolean
--   POST every accepted-but-lost dispatch (all orders) to /delivery-hooks/notify-missed-dispatches; returns true once posted.
--   Data: reads delivery_detail, delivery_dispatch, ordelo_config.
--   HTTP: POST /delivery-hooks/notify-missed-dispatches -> watomation/routers/delivery_hooks.py::notify_missed_dispatches_hook
-- ---------------------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS notify_missed_dispatches ();

CREATE OR REPLACE FUNCTION notify_missed_dispatches ()
    RETURNS boolean
    AS $$
DECLARE
    response json;
    webhook_payload json;
    notified boolean := FALSE;
    app_url varchar;
    hook_url varchar;
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
    hook_url := app_url || '/delivery-hooks/notify-missed-dispatches';
    response := (
        SELECT
            content
        FROM
            http_post (hook_url, webhook_payload::text, 'application/json'));
    -- Log the response
    RAISE NOTICE 'Response from notify-missed-dispatches: %', response;
    notified := TRUE;

    RETURN notified;
END;
$$
LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.notify_missed_dispatches () IS 'POST every accepted-but-lost dispatch (all orders) to /delivery-hooks/notify-missed-dispatches; returns true once posted.';
