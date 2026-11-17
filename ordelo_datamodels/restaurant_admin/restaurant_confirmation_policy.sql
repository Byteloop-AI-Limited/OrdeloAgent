-- =============================================================================================
-- ordelo_datamodels/restaurant_admin/restaurant_confirmation_policy.sql
-- What silence means for one restaurant: how long admins have to answer a new order, and what happens if nobody does.
-- =============================================================================================
-- LIVE CHECK    not yet applied to live (prepared 2026-11-16; the owner applies it, see migrations/restaurant_confirmation_timeout_action.sql).
-- OBJECTS       fn     restaurant_confirmation_policy(p_rest_ref text, OUT timeout_minutes numeric, OUT timeout_action text) -> record
--                   Return (timeout_minutes, timeout_action) for one restaurant; timeout_action is 'accept' or 'decline'.
-- REQUIRES      core/ordelo_config.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none (reads ordelo_config)
-- HOW IT FITS   Restaurant confirmation (see docs/pickup_time_logic.md, "Three confirmation modes"):
--                 auto_accept (restaurant_master) decides whether anyone is ASKED.
--                 This function decides what SILENCE means for restaurants that are asked:
--                   timeout_action 'accept'  -> process_restaurant_confirmation() marks 'restaurant_timedout'; Python auto-accepts
--                   timeout_action 'decline' -> a never-answered order becomes 'auto_decline' + status 'declined'
--                 Two callers read it so the deadline the customer sees is the deadline that is enforced:
--                   process_restaurant_confirmation() (cron, every 10 s) and the web order view (customer countdown).
-- LIFECYCLE     none (stateless; reads configuration)
-- CALLED BY     restaurant_confirmation_policy:
--                 sql       process_restaurant_confirmation() (restaurant_admin/process_restaurant_confirmation.sql)
--                 python    utils_common/web_ordering/customer_order_view.py: get_view()
-- PYTHON MODEL  none
-- SECURITY      restaurant_confirmation_policy(): executable by PUBLIC (default), like the other config readers (parse_alert_offsets).
--               It returns two settings only, no secrets.
-- TESTS         tests/sql/test_restaurant_confirmation_timeout_sql.py
-- GOTCHAS       There is deliberately NO global action key: a global 'decline' would silently flip every WhatsApp restaurant.
--               A non-numeric timeout value raises (same as the job did before this function existed).
-- SEE ALSO      restaurant_admin/process_restaurant_confirmation.sql
--               docs/pickup_time_logic.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function restaurant_confirmation_policy(p_rest_ref text) -> (timeout_minutes numeric, timeout_action text)
--   What silence means for one restaurant: how long admins have to answer, and what happens if nobody does.
--   timeout_minutes: <REF>_RESTAURANT_CONFIRMATION_TIMEOUT_TIME, else RESTAURANT_CONFIRMATION_TIMEOUT_TIME, else 5.
--   timeout_action : 'decline' only when <REF>_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION is 'decline' (any case, trimmed);
--                    everything else, including a missing key, is 'accept'. There is deliberately NO global action key.
--   Always returns exactly one row. Reads ordelo_config. Not consulted for configured auto-accept restaurants
--   (restaurant_master.auto_accept): their orders are never unconfirmed.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_confirmation_policy (p_rest_ref text, OUT timeout_minutes numeric, OUT timeout_action text)
    LANGUAGE sql
    STABLE
    AS $$
    SELECT
        COALESCE((
            SELECT
                config_value::numeric
            FROM
                public.ordelo_config
            WHERE
                config_key = p_rest_ref || '_RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1), (
            SELECT
                config_value::numeric
            FROM
                public.ordelo_config
            WHERE
                config_key = 'RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1), 5),
    CASE WHEN lower(btrim(COALESCE((
                SELECT
                    config_value
                FROM public.ordelo_config
                WHERE
                    config_key = p_rest_ref || '_RESTAURANT_CONFIRMATION_TIMEOUT_ACTION' LIMIT 1), ''))) = 'decline' THEN
        'decline'
    ELSE
        'accept'
    END
$$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): applied to live only with owner approval.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.restaurant_confirmation_policy (text) IS 'Confirmation timeout policy for one restaurant: minutes to answer and what silence means (accept | decline).';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================
-- SELECT * FROM public.restaurant_confirmation_policy ('STRK');
-- SELECT rest_ref, (public.restaurant_confirmation_policy (rest_ref::text)).* FROM public.restaurant_master;
