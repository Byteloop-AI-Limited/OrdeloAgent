-- =============================================================================================
-- ordelo_datamodels/telegram/t_housekeeping.sql
-- Daily purge of old Telegram rows: t_inbox, closed t_sent_messages and finished t_order_alerts.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16). The function exists but is NOT scheduled (no cron.job row): see GOTCHAS.
-- OBJECTS       fn     t_housekeeping() -> jsonb
--                   Delete Telegram inbox, ledger and schedule rows older than their retention settings; returns the counts as jsonb.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  When run: deletes old rows from t_inbox, t_sent_messages and t_order_alerts.
-- HOW IT FITS   Meant to run from pg_cron once a day (planned '20 3 * * *'); deletes t_inbox rows older than TGRAM_INBOX_RETENTION_DAYS (7) and
--                 closed ledger / finished schedule rows older than TGRAM_LEDGER_RETENTION_DAYS (30).
--                 Overview of the whole Telegram layer: docs/telegram-layer.md (and its HTML companion).
-- LIFECYCLE     none
-- CALLED BY     t_housekeeping:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      t_housekeeping(): service role only
-- TESTS         tests/sql/test_order_cards_sql.py (loads this file into a throwaway Postgres)
--               tests/sql/test_order_cards_sql.py
--               tests/sql/test_restaurant_ready_adjust_notices_sql.py
-- GOTCHAS       Not scheduled on live, so the tables are never trimmed (docs/to-do.md). Schedule with:
--               SELECT cron.schedule('t_housekeeping', '20 3 * * *', 'SELECT public.t_housekeeping()');
-- SEE ALSO      telegram/t_inbox.sql
--               telegram/t_sent_messages.sql
--               telegram/t_order_alerts.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function t_housekeeping() -> jsonb
--   Delete Telegram inbox, ledger and schedule rows older than their retention settings; returns the counts as jsonb.
--   Data: reads ordelo_config; writes t_inbox, t_order_alerts, t_sent_messages.
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 12. t_housekeeping(): daily purge (D22). Returns jsonb counts. Retention comes from ordelo_config.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_housekeeping ()
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_inbox_days int;
    v_ledger_days int;
    n_inbox int;
    n_ledger int;
    n_alerts int;
BEGIN
    SELECT
        COALESCE((
            SELECT
                config_value::int
            FROM public.ordelo_config
            WHERE
                config_key = 'TGRAM_INBOX_RETENTION_DAYS'
                AND config_value ~ '^\s*\d+\s*$'), 7) INTO v_inbox_days;
    SELECT
        COALESCE((
            SELECT
                config_value::int
            FROM public.ordelo_config
            WHERE
                config_key = 'TGRAM_LEDGER_RETENTION_DAYS'
                AND config_value ~ '^\s*\d+\s*$'), 30) INTO v_ledger_days;

    DELETE FROM public.t_inbox
    WHERE received_at < now() - make_interval(days => v_inbox_days);
    GET DIAGNOSTICS n_inbox = ROW_COUNT;
    DELETE FROM public.t_sent_messages
    WHERE state = 'closed'
        AND closed_at < now() - make_interval(days => v_ledger_days);
    GET DIAGNOSTICS n_ledger = ROW_COUNT;
    DELETE FROM public.t_order_alerts
    WHERE status <> 'pending'
        AND created_at < now() - make_interval(days => v_ledger_days);
    GET DIAGNOSTICS n_alerts = ROW_COUNT;

    RETURN jsonb_build_object('t_inbox', n_inbox, 't_sent_messages', n_ledger, 't_order_alerts', n_alerts);
END
$$;

REVOKE ALL ON FUNCTION public.t_housekeeping () FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.t_housekeeping () IS 'Delete Telegram inbox, ledger and schedule rows older than their retention settings; returns the counts as jsonb.';
