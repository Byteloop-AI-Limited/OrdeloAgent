-- MIGRATION (history; do not edit the statements below)
-- Applied to live: NOT YET (prepared 2026-11-17; the owner applies it himself)
-- Current definitions now live in: restaurant_admin/process_restaurant_confirmation.sql
-- Purpose: 15-second pickup grace. An order an admin ACCEPTED but gave no pickup time is timed out ('restaurant_timedout', then
--          Python applies the default pickup time) 15 seconds after the accept, instead of waiting for the full confirmation
--          timeout (3 minutes at STRK). Measured from restaurant_update_dtts, which restaurant_order_decide() stamps on accept
--          (WhatsApp and Telegram alike). Never later than the usual timeout. Fixed in code (c_pickup_grace), not a config key,
--          by owner decision. Unanswered orders, auto-decline and the customer countdown are unchanged. With the cron every
--          10 seconds the grace takes effect 15 to 25 seconds after the accept.
--          No table, index, constraint, trigger, grant or cron change: one CREATE OR REPLACE FUNCTION.
-- Requires: migrations/restaurant_confirmation_timeout_action.sql already applied (uses restaurant_confirmation_policy()).

/*
HOW TO APPLY (Supabase SQL editor; no BEGIN/COMMIT):

  STEP 0  PRE-CHECK (read only): expect has_grace_before = false.
  STEP 1  The function. CREATE OR REPLACE, safe to re-run; the pg_cron job keeps running and picks it up on its next run.
  STEP 2  VERIFY (read only): expect has_grace_after = true.
  STEP 3  python scripts/datamodels/drift_check.py
  STEP 4  Live test: place a STRK order, tap Accept, do not pick a time. Expect the default pickup time and the
          auto-accept notice about 15-25 seconds after the tap (not at 3 minutes).
  ROLLBACK  Re-run the previous git version of restaurant_admin/process_restaurant_confirmation.sql (the function only).
*/

-- STEP 0  PRE-CHECK (read only)
SELECT
    position('c_pickup_grace' IN pg_get_functiondef('public.process_restaurant_confirmation()'::regprocedure)) > 0 AS has_grace_before;

-- STEP 1  Function (same body as restaurant_admin/process_restaurant_confirmation.sql)
CREATE OR REPLACE FUNCTION process_restaurant_confirmation ()
    RETURNS TABLE (
        action text)
    LANGUAGE plpgsql
    AS $$
DECLARE
    -- An admin who accepted has this long to choose a pickup time before the default is applied.
    -- Fixed on purpose (owner, 17 Nov 2026): the same for every restaurant, not a config key.
    c_pickup_grace CONSTANT interval := interval '15 seconds';
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
        AND (
            -- The usual timeout, measured from the order (unanswered, or accepted without an accept stamp).
            (EXTRACT(EPOCH FROM (NOW() - ds.dtts)) / 60) > (public.restaurant_confirmation_policy (ds.rest_ref::text)).timeout_minutes
            -- Accepted but no pickup time: only the grace period, measured from the accept.
            OR (ds.restaurant_confirmation_status = 'restaurant_accept'
                AND ds.restaurant_update_dtts IS NOT NULL
                AND NOW() - ds.restaurant_update_dtts > c_pickup_grace))
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
        AND (
            -- The usual timeout, measured from the order (unanswered, or accepted without an accept stamp).
            (EXTRACT(EPOCH FROM (NOW() - ts.dtts)) / 60) > (public.restaurant_confirmation_policy (ts.rest_ref::text)).timeout_minutes
            -- Accepted but no pickup time: only the grace period, measured from the accept.
            OR (ts.restaurant_confirmation_status = 'restaurant_accept'
                AND ts.restaurant_update_dtts IS NOT NULL
                AND NOW() - ts.restaurant_update_dtts > c_pickup_grace))
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

-- STEP 2  VERIFY (read only)
SELECT
    position('c_pickup_grace' IN pg_get_functiondef('public.process_restaurant_confirmation()'::regprocedure)) > 0 AS has_grace_after;
