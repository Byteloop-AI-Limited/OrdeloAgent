-- =============================================================================================
-- ordelo_datamodels/restaurant_admin/job_restaurant_confirmation_timeout.sql
-- Older timeout job: default the prep time to 25 minutes and make unconfirmed orders dispatchable (NOT scheduled).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16). Not scheduled and no callers found: see GOTCHAS.
-- OBJECTS       fn     job_restaurant_confirmation_timeout(p_rest_ref character varying) -> TABLE(action text)
--                   Time out unconfirmed delivery orders (optionally one restaurant) with a 25-minute default prep time; returns what changed.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  If called: sets status 'unassigned', pickup_time now() + 25 min and the timeout fields on overdue delivery orders.
-- HOW IT FITS   Restaurant confirmation, delivery and takeaway alike:
--                 new order -> init_delivery() / init_takeaway() -> resolve_initial_restaurant_acceptance():
--                     auto_accept restaurants: order starts accepted with a default pickup time (no prompt)
--                     otherwise: 'restaurant_unconfirmed' -> trigger -> admins prompted (WhatsApp buttons; Telegram order cards)
--                 admin taps Accept / Decline -> restaurant_order_decide(); picks a pickup time -> restaurant_order_set_pickup()
--                     (Telegram taps go through t_order_decide() / t_order_set_pickup(), which authorise the person first)
--                 no answer -> process_restaurant_confirmation() (cron 10 s) -> 'restaurant_timedout' -> trigger -> Python sets a default
--                     pickup time and makes the order dispatchable (delivery_hooks._handle_restaurant_timedout)
--                 morning check -> enquire_admin_availability() (cron 11:00 UTC) asks admins whether the restaurant is open today.
--                 This function predates process_restaurant_confirmation() and is not scheduled on live; nothing calls it.
-- LIFECYCLE     none
-- CALLED BY     job_restaurant_confirmation_timeout:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      job_restaurant_confirmation_timeout(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       Not in cron.job; process_restaurant_confirmation() is the timeout that runs. Decide whether to drop it (docs/to-do.md).
--               Uses different config keys (<REST>_RESTAURANT_CONFIRMATION_TIMEOUT, no _TIME suffix).
--               The body was taken from live on 2026-10-16: the previous repo copy differed.
-- SEE ALSO      restaurant_admin/process_restaurant_confirmation.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function job_restaurant_confirmation_timeout(p_rest_ref character varying) -> TABLE(action text)
--   Time out unconfirmed delivery orders (optionally one restaurant) with a 25-minute default prep time; returns what changed.
--   Data: reads ordelo_config; writes delivery_summary.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_restaurant_confirmation_timeout (p_rest_ref character varying DEFAULT NULL::character varying)
    RETURNS TABLE (
        action text)
    LANGUAGE plpgsql
    AS $function$
BEGIN
    RETURN QUERY WITH timeout_config AS (
        -- Get timeout value: restaurant-specific first, then default
        SELECT
            ds.order_number,
            ds.rest_id,
            COALESCE((
                SELECT
                    config_value::numeric
                FROM ordelo_config
                WHERE
                    config_key = SPLIT_PART(ds.order_number, '-', 1) || '_RESTAURANT_CONFIRMATION_TIMEOUT' LIMIT 1), (
                SELECT
                    config_value::numeric
                FROM ordelo_config
                WHERE
                    config_key = 'RESTAURANT_CONFIRMATION_TIMEOUT' LIMIT 1), 5 -- Fallback to 5 minutes if no config found
) AS timeout_minutes
        FROM
            delivery_summary ds
        WHERE
            ds.status = 'restaurant_unconfirmed'
            OR ds.status = 'restaurant_accept'
            AND (p_rest_ref IS NULL
                OR SPLIT_PART(ds.order_number, '-', 1) = p_rest_ref)),
    timed_out_orders AS (
        UPDATE
            delivery_summary ds
        SET
            status = 'unassigned',
            rest_confirmed_at = NOW(),
            rest_prep_time_minutes = 25, -- Default to max time
            rest_confirmation_method = 'timeout',
            pickup_time = NOW() + INTERVAL '25 minutes'
        FROM
            timeout_config tc
        WHERE
            ds.order_number = tc.order_number
            AND (ds.status = 'restaurant_unconfirmed'
                OR ds.status = 'restaurant_accept')
            AND (EXTRACT(EPOCH FROM (NOW() - ds.dtts)) / 60) >= tc.timeout_minutes
        RETURNING
            ds.order_number,
            ds.rest_id,
            tc.timeout_minutes,
            'Order ' || ds.order_number || ' → restaurant confirmation timed out after ' || tc.timeout_minutes || ' minutes, defaulted to 25min prep time' AS action
)
SELECT
    timed_out_orders.action
FROM
    timed_out_orders;
END;
$function$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.job_restaurant_confirmation_timeout (p_rest_ref character varying) IS 'Time out unconfirmed delivery orders (optionally one restaurant) with a 25-minute default prep time; returns what changed.';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- Example: Process specific restaurant
-- SELECT * FROM job_restaurant_confirmation_timeout('ELAS');

-- Example: Process all restaurants
-- SELECT * FROM job_restaurant_confirmation_timeout();
-- Show definition of this postgres function
-- SELECT pg_get_functiondef('job_restaurant_confirmation_timeout'::regproc);
