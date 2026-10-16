-- =============================================================================================
-- ordelo_datamodels/restaurant_admin/process_restaurant_confirmation.sql
-- Every 10 seconds: time out restaurant confirmations nobody answered (delivery and takeaway).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     process_restaurant_confirmation() -> TABLE(action text)
--                   Mark overdue unanswered restaurant confirmations 'restaurant_timedout' for delivery and takeaway; returns the orders it changed.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each run sets restaurant_confirmation_status = 'restaurant_timedout' on overdue orders, which fires the restaurant
--               trigger (POST .../restaurant-confirmation-request, trigger_reason 'restaurant_timedout').
-- HOW IT FITS   Restaurant confirmation, delivery and takeaway alike:
--                 new order -> init_delivery() / init_takeaway() -> resolve_initial_restaurant_acceptance():
--                     auto_accept restaurants: order starts accepted with a default pickup time (no prompt)
--                     otherwise: 'restaurant_unconfirmed' -> trigger -> admins prompted (WhatsApp buttons; Telegram order cards)
--                 admin taps Accept / Decline -> restaurant_order_decide(); picks a pickup time -> restaurant_order_set_pickup()
--                     (Telegram taps go through t_order_decide() / t_order_set_pickup(), which authorise the person first)
--                 no answer -> process_restaurant_confirmation() (cron 10 s) -> 'restaurant_timedout' -> trigger -> Python sets a default
--                     pickup time and makes the order dispatchable (delivery_hooks._handle_restaurant_timedout)
--                 morning check -> enquire_admin_availability() (cron 11:00 UTC) asks admins whether the restaurant is open today.
-- LIFECYCLE     An order times out when restaurant_confirmation_status is 'restaurant_unconfirmed' or 'restaurant_accept', pickup_time
--               is still NULL, and it is older than <REST>_RESTAURANT_CONFIRMATION_TIMEOUT_TIME (else RESTAURANT_CONFIRMATION_TIMEOUT_TIME,
--               else 5) minutes. Python then sets the default pickup time (+30 min) and moves the order on.
-- CALLED BY     process_restaurant_confirmation:
--                 cron      'process_restaurant_confirmation' 10 seconds
-- PYTHON MODEL  none
-- SECURITY      process_restaurant_confirmation(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       Older notes say every 5 seconds; the live schedule is every 10 seconds.
--               A decision tap and this timeout can race: restaurant_order_decide() only changes an undecided row, so whichever
--                 UPDATE commits first wins and the other changes nothing.
-- SEE ALSO      restaurant_admin/restaurant_order_decision.sql
--               delivery/delivery_summary.sql (trigger_restaurant_updates)
--               docs/pickup_time_logic.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function process_restaurant_confirmation() -> TABLE(action text)
--   Mark overdue unanswered restaurant confirmations 'restaurant_timedout' for delivery and takeaway; returns the orders it changed.
--   Data: reads ordelo_config; writes delivery_summary, takeaway_summary.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION process_restaurant_confirmation ()
    RETURNS TABLE (
        action text)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY WITH delivery_timedout_confirmations AS (
        -- Update delivery orders where restaurant hasn't completed confirmation in time
        UPDATE
            delivery_summary ds
        SET
            restaurant_confirmation_status = 'restaurant_timedout',
            restaurant_update_dtts = NOW()
        WHERE
            ds.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept')
            AND ds.pickup_time IS NULL
            AND (EXTRACT(EPOCH FROM (NOW() - ds.dtts)) / 60) > COALESCE((
                SELECT
                    config_value::numeric
                FROM ordelo_config
                WHERE
                    config_key = ds.rest_ref || '_RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1), (
                SELECT
                    config_value::numeric
                FROM ordelo_config
                WHERE
                    config_key = 'RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1), 5 -- fallback to 5 minutes if no config found
)
        RETURNING
            ds.order_number,
            ds.rest_ref,
            ds.restaurant_confirmation_status,
            'Delivery order ' || ds.order_number || ' (' || ds.rest_ref || ') → restaurant_confirmation_status set to restaurant_timedout' AS action
),
takeaway_timedout_confirmations AS (
    -- Update takeaway orders where restaurant hasn't completed confirmation in time
    UPDATE
        takeaway_summary ts
    SET
        restaurant_confirmation_status = 'restaurant_timedout',
        restaurant_update_dtts = NOW()
    WHERE
        ts.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept')
        AND ts.pickup_time IS NULL
        AND (EXTRACT(EPOCH FROM (NOW() - ts.dtts)) / 60) > COALESCE((
            SELECT
                config_value::numeric
            FROM ordelo_config
        WHERE
            config_key = ts.rest_ref || '_RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1), (
        SELECT
            config_value::numeric
        FROM ordelo_config
    WHERE
        config_key = 'RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1), 5 -- fallback to 5 minutes if no config found
)
    RETURNING
        ts.order_number,
        ts.rest_ref,
        ts.restaurant_confirmation_status,
        'Takeaway order ' || ts.order_number || ' (' || ts.rest_ref || ') → restaurant_confirmation_status set to restaurant_timedout' AS action
)
SELECT
    dc.action
FROM
    delivery_timedout_confirmations dc
UNION ALL
SELECT
    tc.action
FROM
    takeaway_timedout_confirmations tc;
END;
$$;

-- pg_cron job 'process_restaurant_confirmation': runs every 10 seconds, active on live.
-- cron.schedule() with an existing job name updates that job in place, so re-running is safe.
SELECT
    cron.schedule ('process_restaurant_confirmation', '10 seconds', 'SELECT public.process_restaurant_confirmation()');

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.process_restaurant_confirmation () IS 'Mark overdue unanswered restaurant confirmations ''restaurant_timedout'' for delivery and takeaway; returns the orders it changed.';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- Schedule this function to run every 5 seconds via pg_cron
-- SELECT cron.schedule('process_restaurant_confirmation', '*/5 * * * * *', 'SELECT * FROM process_restaurant_confirmation()');

-- To unschedule:
-- SELECT cron.unschedule('process_restaurant_confirmation');

-- Manual test:
-- SELECT * FROM process_restaurant_confirmation();
