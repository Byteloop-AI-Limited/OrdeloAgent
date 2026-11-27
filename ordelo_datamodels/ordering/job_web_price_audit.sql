-- =============================================================================================
-- ordelo_datamodels/ordering/job_web_price_audit.sql
-- Daily at 00:05 UTC: wake OrdeloAgent to run the web price-floor audit (ADR 0019).
-- =============================================================================================
-- LIVE CHECK    not applied yet (plans/telegram-rider-invite-alert-schedule.md, phase 2).
-- OBJECTS       fn     job_web_price_audit() -> boolean
--                   POST /web-hooks/price-audit once a day; true when the app answered 2xx.
-- REQUIRES      platform/app_hook_post.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run (cron.schedule with an existing name updates in place).
-- SIDE EFFECTS  Schedules the pg_cron job 'job_web_price_audit' (daily at 00:05 UTC). Exactly one HTTP POST per run. Writes nothing:
--                 the Python sweep owns every claim and update.
-- HOW IT FITS   this job (00:05 UTC) -> app_hook_post -> /web-hooks/price-audit -> web_ordering/monitoring.sweep(): claim
--                 today's web_monitor_run row (London date), compare the last 24 hours of web order lines with the menu
--                 floor, record flagged orders and alert ops. Prices are never changed.
-- LIFECYCLE     none: this job keeps no state. Audit claim states: ordering/web_monitor_run.sql.
-- CALLED BY     job_web_price_audit:
--                 cron      'job_web_price_audit' 5 0 * * *
-- PYTHON MODEL  watomation/routers/sweep_hooks.py: web_price_audit(); utils_common/web_ordering/monitoring.py: sweep()
-- SECURITY      PUBLIC, anon and authenticated revoked; service role only.
-- TESTS         tests/sql/test_customer_sweep_jobs_sql.py
--               tests/watomation/routers/test_sweep_hooks.py
-- GOTCHAS       web_monitor_run allows one run per London date: a second call that day returns without work. 00:05 UTC is
--               00:05 or 01:05 London, so it never falls on the previous London date. A failed audit deletes its
--               claim; the retry is the next day's run, or SELECT public.job_web_price_audit() by hand the same day.
--               Keep the app_hook_post() result in a variable: BETWEEN repeats its operand, so a volatile call would POST twice.
-- SEE ALSO      docs/adr/0019-scheduled-work-is-owned-by-pg-cron.md
--               docs/to-do.md
--               ordering/web_monitor_run.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function job_web_price_audit() -> boolean
--   Wake the daily price audit: POST {event_type: 'web_price_audit'} to /web-hooks/price-audit through app_hook_post().
--   The sweep claims the London date itself, so an extra call the same day does nothing.
--   Returns true when the app answered 2xx; false on any other status or when the call failed (app_hook_post never
--   raises and returns NULL on failure). The route answers at once and runs the sweep in BackgroundTasks, so true means
--   "the app accepted the wake-up", not "the sweep succeeded".
--   Data: reads and writes nothing itself. HTTP: POST {ORDELO_APP_URL}/web-hooks/price-audit with {"event_type": "web_price_audit"}.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_web_price_audit ()
    RETURNS boolean
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_status integer;
BEGIN
    -- Into a variable first: "app_hook_post(...) BETWEEN 200 AND 299" would expand to two calls, so two POSTs.
    v_status := public.app_hook_post('/web-hooks/price-audit',
        jsonb_build_object('event_type', 'web_price_audit'));
    RETURN coalesce(v_status BETWEEN 200 AND 299, FALSE);
END;
$$;

REVOKE ALL ON FUNCTION public.job_web_price_audit () FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.job_web_price_audit () TO service_role;
COMMENT ON FUNCTION public.job_web_price_audit () IS 'Daily 00:05 UTC: POST /web-hooks/price-audit (one web price-floor audit per London day).';

-- pg_cron job 'job_web_price_audit': runs every 5 0 * * * (00:05 UTC), INACTIVE on live until the owner applies this file (plan phase 2).
SELECT cron.schedule('job_web_price_audit', '5 0 * * *', 'SELECT public.job_web_price_audit()');
-- To stop:    SELECT cron.unschedule('job_web_price_audit');
-- To inspect: SELECT status, start_time, return_message FROM cron.job_run_details
--             WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'job_web_price_audit') ORDER BY start_time DESC LIMIT 10;
