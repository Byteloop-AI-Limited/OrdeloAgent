-- =============================================================================================
-- ordelo_datamodels/restaurant_admin/process_restaurant_confirmation.sql
-- Every 10 seconds: time out restaurant confirmations nobody answered (delivery and takeaway).
-- =============================================================================================
-- LIVE CHECK    last compared with the live catalogue 2026-10-16; the auto_decline change (2026-11-16) is not yet applied to live
--               (migrations/restaurant_confirmation_timeout_action.sql; the owner applies it).
-- OBJECTS       fn     process_restaurant_confirmation() -> TABLE(action text)
--                   Mark overdue unanswered restaurant confirmations for delivery and takeaway: 'restaurant_timedout', or 'auto_decline' + status 'declined'
--                   where the restaurant declines on silence; returns the orders it changed.
-- REQUIRES      restaurant_admin/restaurant_confirmation_policy.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each run sets restaurant_confirmation_status to 'restaurant_timedout' (or 'auto_decline', with status 'declined') on overdue
--               orders, which fires the restaurant trigger (POST .../restaurant-confirmation-request, trigger_reason 'restaurant_timedout'
--               or 'auto_decline').
-- HOW IT FITS   Restaurant confirmation, delivery and takeaway alike:
--                 new order -> init_delivery() / init_takeaway() -> resolve_initial_restaurant_acceptance():
--                     auto_accept restaurants: order starts accepted with a default pickup time (no prompt)
--                     otherwise: 'restaurant_unconfirmed' -> trigger -> admins prompted (WhatsApp buttons; Telegram order cards)
--                 admin taps Accept / Decline -> restaurant_order_decide(); picks a pickup time -> restaurant_order_set_pickup()
--                     (Telegram taps go through t_order_decide() / t_order_set_pickup(), which authorise the person first)
--                 no answer -> process_restaurant_confirmation() (cron 10 s), which asks restaurant_confirmation_policy() what silence means:
--                     'accept'  -> 'restaurant_timedout' -> trigger -> Python sets a default pickup time and makes the order dispatchable
--                                  (delivery_hooks._handle_restaurant_timedout)
--                     'decline' -> a never-answered order becomes 'auto_decline' + status 'declined' -> trigger -> Python tells the customer,
--                                  releases the payment and notifies admins and overwatch (_handle_restaurant_decline, timed_out=True)
--                     an order an admin ACCEPTED without choosing a pickup time is always 'restaurant_timedout' (auto-accepted)
--                 morning check -> enquire_admin_availability() (cron 11:00 UTC) asks admins whether the restaurant is open today.
-- LIFECYCLE     An order times out when restaurant_confirmation_status is 'restaurant_unconfirmed' or 'restaurant_accept', pickup_time
--               is still NULL, and it is older than the policy's timeout_minutes (<REST>_RESTAURANT_CONFIRMATION_TIMEOUT_TIME, else
--               RESTAURANT_CONFIRMATION_TIMEOUT_TIME, else 5). 'restaurant_unconfirmed' + timeout_action 'decline' -> 'auto_decline' and
--               status 'declined' (terminal). Otherwise 'restaurant_timedout'; Python then sets the default pickup time and moves the order on.
-- CALLED BY     process_restaurant_confirmation:
--                 cron      'process_restaurant_confirmation' 10 seconds
-- PYTHON MODEL  none
-- SECURITY      process_restaurant_confirmation(): executable by PUBLIC (default)
-- TESTS         tests/sql/test_restaurant_confirmation_timeout_sql.py
-- GOTCHAS       Older notes say every 5 seconds; the live schedule is every 10 seconds.
--               A decision tap and this timeout can race: restaurant_order_decide() only changes an undecided row, so whichever
--                 UPDATE commits first wins and the other changes nothing.
-- SEE ALSO      restaurant_admin/restaurant_confirmation_policy.sql
--               restaurant_admin/restaurant_order_decision.sql
--               delivery/delivery_summary.sql (trigger_restaurant_updates)
--               docs/pickup_time_logic.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function process_restaurant_confirmation() -> TABLE(action text)
--   Mark overdue unanswered restaurant confirmations for delivery and takeaway ('restaurant_timedout', or 'auto_decline' + status 'declined'
--   where the restaurant declines on silence); returns the orders it changed.
--   Data: calls restaurant_confirmation_policy() (reads ordelo_config); writes delivery_summary, takeaway_summary.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION process_restaurant_confirmation ()
    RETURNS TABLE (
        action text)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY WITH delivery_timedout_confirmations AS (
        -- Delivery orders whose restaurant has not completed confirmation in time
    UPDATE
        delivery_summary ds
    SET
        -- Never answered and the restaurant declines on silence: terminal decline in this same UPDATE.
        -- Everything else (timeout action 'accept', or an admin accepted but chose no pickup time): as before.
        restaurant_confirmation_status = CASE WHEN ds.restaurant_confirmation_status = 'restaurant_unconfirmed'
            AND (public.restaurant_confirmation_policy (ds.rest_ref::text)).timeout_action = 'decline' THEN
            'auto_decline'
        ELSE
            'restaurant_timedout'
        END,
        status = CASE WHEN ds.restaurant_confirmation_status = 'restaurant_unconfirmed'
            AND (public.restaurant_confirmation_policy (ds.rest_ref::text)).timeout_action = 'decline' THEN
            'declined'
        ELSE
            ds.status
        END,
        restaurant_update_dtts = NOW()
    WHERE
        ds.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept')
        AND ds.pickup_time IS NULL
        AND (EXTRACT(EPOCH FROM (NOW() - ds.dtts)) / 60) > (public.restaurant_confirmation_policy (ds.rest_ref::text)).timeout_minutes
    RETURNING
        ds.order_number,
        ds.rest_ref,
        ds.restaurant_confirmation_status,
        'Delivery order ' || ds.order_number || ' (' || ds.rest_ref || ') → restaurant_confirmation_status set to ' || ds.restaurant_confirmation_status AS action
),
takeaway_timedout_confirmations AS (
    -- Takeaway orders whose restaurant has not completed confirmation in time
    UPDATE
        takeaway_summary ts
    SET
        -- Never answered and the restaurant declines on silence: terminal decline in this same UPDATE.
        -- Everything else (timeout action 'accept', or an admin accepted but chose no pickup time): as before.
        restaurant_confirmation_status = CASE WHEN ts.restaurant_confirmation_status = 'restaurant_unconfirmed'
            AND (public.restaurant_confirmation_policy (ts.rest_ref::text)).timeout_action = 'decline' THEN
            'auto_decline'
        ELSE
            'restaurant_timedout'
        END,
        status = CASE WHEN ts.restaurant_confirmation_status = 'restaurant_unconfirmed'
            AND (public.restaurant_confirmation_policy (ts.rest_ref::text)).timeout_action = 'decline' THEN
            'declined'
        ELSE
            ts.status
        END,
        restaurant_update_dtts = NOW()
    WHERE
        ts.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept')
        AND ts.pickup_time IS NULL
        AND (EXTRACT(EPOCH FROM (NOW() - ts.dtts)) / 60) > (public.restaurant_confirmation_policy (ts.rest_ref::text)).timeout_minutes
    RETURNING
        ts.order_number,
        ts.rest_ref,
        ts.restaurant_confirmation_status,
        'Takeaway order ' || ts.order_number || ' (' || ts.rest_ref || ') → restaurant_confirmation_status set to ' || ts.restaurant_confirmation_status AS action
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
COMMENT ON FUNCTION public.process_restaurant_confirmation () IS 'Mark overdue unanswered restaurant confirmations for delivery and takeaway: ''restaurant_timedout'', or ''auto_decline'' + status ''declined'' where the restaurant declines on silence; returns the orders it changed.';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- Schedule this function to run every 5 seconds via pg_cron
-- SELECT cron.schedule('process_restaurant_confirmation', '*/5 * * * * *', 'SELECT * FROM process_restaurant_confirmation()');

-- To unschedule:
-- SELECT cron.unschedule('process_restaurant_confirmation');

-- Manual test:
-- SELECT * FROM process_restaurant_confirmation();
