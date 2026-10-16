-- =============================================================================================
-- ordelo_datamodels/_orphans/restaurant_admin.sql
-- Unused live function from the restaurant confirmation area.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16). Orphan candidates: live, no caller found.
-- OBJECTS       fn     handle_restaurant_confirmation(p_order_number character varying, p_prep_time_minutes integer) -> boolean
--                   Earlier handler that set an unconfirmed order to 'unassigned' with a prep time and called process_delivery(); the decision RPCs replaced it.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none when applied. Functions that make HTTP calls or change rows only do so if someone calls them.
-- HOW IT FITS   Orphan candidates (Gate 1 decision D1): objects that exist on live but that nothing calls. A search on 2026-10-16 found
--                 no reference in OrdeloAgent, restaurant-frontend or restaurant-agents code, in any other live function or view, in a
--                 trigger or in a pg_cron job. They are captured here exactly as live so the repo describes the whole database.
--                 Nothing has been dropped: deciding keep or drop is an owner decision (docs/to-do.md). Before dropping one, re-check
--                 for callers outside these three repos (other services, manual scripts, Supabase Studio).
-- LIFECYCLE     none
-- CALLED BY     handle_restaurant_confirmation:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      handle_restaurant_confirmation(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       Its old repo copy (which differs from live) is in _archive/_tbd_handle_restaurant_confirmation.sql.
-- SEE ALSO      docs/to-do.md (decide on orphan candidates)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function handle_restaurant_confirmation(p_order_number character varying, p_prep_time_minutes integer) -> boolean
--   Earlier handler that set an unconfirmed order to 'unassigned' with a prep time and called process_delivery(); the decision RPCs replaced it.
--   Data: writes delivery_summary; calls process_delivery().
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.handle_restaurant_confirmation (p_order_number character varying, p_prep_time_minutes integer)
    RETURNS boolean
    LANGUAGE plpgsql
    AS $function$
DECLARE
    v_updated boolean;
BEGIN
    -- Update delivery_summary
    UPDATE
        delivery_summary
    SET
        status = 'unassigned',
        rest_confirmed_at = NOW(),
        rest_prep_time_minutes = p_prep_time_minutes,
        rest_confirmation_method = 'manual',
        pickup_time = NOW() + (p_prep_time_minutes || ' minutes')::interval
    WHERE
        order_number = p_order_number
        AND status = 'restaurant_unconfirmed'
    RETURNING
        TRUE INTO v_updated;
    IF v_updated THEN
        -- Trigger process_delivery for this order
        PERFORM
            process_delivery ();
        RAISE NOTICE 'Restaurant confirmed % minutes for order %', p_prep_time_minutes, p_order_number;
        RETURN TRUE;
    ELSE
        RAISE NOTICE 'Order % not found or already confirmed', p_order_number;
        RETURN FALSE;
    END IF;
END;
$function$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.handle_restaurant_confirmation (p_order_number character varying, p_prep_time_minutes integer) IS 'Earlier handler that set an unconfirmed order to ''unassigned'' with a prep time and called process_delivery(); the decision RPCs replaced it.';
