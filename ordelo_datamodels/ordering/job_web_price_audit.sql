-- =============================================================================================
-- ordelo_datamodels/ordering/job_web_price_audit.sql
-- Hourly at :05: wake OrdeloAgent to run the web price-floor audit when today's London audit is due (ADR 0019).
-- =============================================================================================
-- LIVE CHECK    function checked at rollout and cron registration verified active (2026-11-27).
-- OBJECTS       fn     job_web_price_audit() -> boolean
--                   POST /web-hooks/price-audit unless today's London web_monitor_run row exists; true when skipped or 2xx.
-- REQUIRES      platform/app_hook_post.sql
--               ordering/web_monitor_run.sql (the due check reads run_day)
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run (cron.schedule with an existing name updates in place).
-- SIDE EFFECTS  Schedules the pg_cron job 'job_web_price_audit' (hourly at :05). At most one HTTP POST per run, none when
--                 today's audit is already claimed. Writes nothing: the Python sweep owns every claim and update.
-- HOW IT FITS   this job (every hour at :05) -> due check: no web_monitor_run row for today's London date -> app_hook_post
--                 -> /web-hooks/price-audit -> web_ordering/monitoring.sweep(): claim today's web_monitor_run row (London
--                 date), compare the last 24 hours of web order lines with the menu floor, record flagged orders and alert
--                 ops. Prices are never changed. The first run of each London day POSTs; the rest of that day skip in SQL.
-- LIFECYCLE     none: this job keeps no state. Audit claim states: ordering/web_monitor_run.sql.
-- CALLED BY     job_web_price_audit:
--                 cron      'job_web_price_audit' 5 * * * *
-- PYTHON MODEL  watomation/routers/sweep_hooks.py: web_price_audit(); utils_common/web_ordering/monitoring.py: sweep()
-- SECURITY      PUBLIC, anon and authenticated revoked; service role only.
-- TESTS         tests/sql/test_customer_sweep_jobs_sql.py
--               tests/watomation/routers/test_sweep_hooks.py
-- GOTCHAS       The due check reads only whether today's London row exists, not completed_at. A failed audit deletes its
--                 claim, so the next hourly run POSTs again (retry within the hour). A crash mid-audit leaves the
--                 unfinished claim behind, so that day is skipped until someone deletes the row; that was already true
--                 of the sweep's own claim before this check.
--               The London date is (now() AT TIME ZONE 'Europe/London')::date, independent of the session TimeZone, so
--                 the 23:05 UTC run during BST already belongs to the next London day.
--               Status handling: see the app_hook_post.sql GOTCHAS (keep the result in a variable).
-- SEE ALSO      docs/adr/0019-scheduled-work-is-owned-by-pg-cron.md
--               docs/to-do.md
--               ordering/web_monitor_run.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function job_web_price_audit() -> boolean
--   Wake the daily price audit when it is due: if web_monitor_run already has a row for today's London date, return
--   true without calling the app. Otherwise POST {event_type: 'web_price_audit'} to /web-hooks/price-audit through
--   app_hook_post(). The sweep claims the London date itself, so a POST that races another claim does nothing.
--   Returns true when skipped or when the app answered 2xx; false on any other status or when the call failed
--   (app_hook_post never raises and returns NULL on failure). The route answers at once and runs the sweep in
--   BackgroundTasks, so true means "not due, or the app accepted the wake-up", not "the sweep succeeded".
--   Data: reads web_monitor_run (run_day). HTTP: POST {ORDELO_APP_URL}/web-hooks/price-audit with {"event_type": "web_price_audit"}.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_web_price_audit ()
    RETURNS boolean
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_status integer;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.web_monitor_run
        WHERE run_day = (now() AT TIME ZONE 'Europe/London')::date) THEN
        RETURN TRUE;
    END IF;
    -- see app_hook_post.sql GOTCHAS
    v_status := public.app_hook_post('/web-hooks/price-audit',
        jsonb_build_object('event_type', 'web_price_audit'));
    RETURN coalesce(v_status BETWEEN 200 AND 299, FALSE);
END;
$$;

REVOKE ALL ON FUNCTION public.job_web_price_audit () FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.job_web_price_audit () TO service_role;
COMMENT ON FUNCTION public.job_web_price_audit () IS 'Hourly at :05: POST /web-hooks/price-audit only when today''s London web_monitor_run row is missing (one audit per London day).';

-- pg_cron job 'job_web_price_audit': runs every 5 * * * * (hourly at :05), active on live.
SELECT cron.schedule('job_web_price_audit', '5 * * * *', 'SELECT public.job_web_price_audit()');
-- To stop:    SELECT cron.unschedule('job_web_price_audit');
-- To inspect: SELECT status, start_time, return_message FROM cron.job_run_details
--             WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'job_web_price_audit') ORDER BY start_time DESC LIMIT 10;
