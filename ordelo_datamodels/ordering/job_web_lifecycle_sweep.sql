-- =============================================================================================
-- ordelo_datamodels/ordering/job_web_lifecycle_sweep.sql
-- Every minute: wake OrdeloAgent to expire web checkouts, prune web counters and release held web payments (ADR 0019).
-- =============================================================================================
-- LIVE CHECK    function checked at rollout and cron registration verified active (2026-11-27).
-- OBJECTS       fn     job_web_lifecycle_sweep() -> boolean
--                   POST /web-hooks/lifecycle-sweep every run; true when the app answered 2xx.
-- REQUIRES      platform/app_hook_post.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run (cron.schedule with an existing name updates in place).
-- SIDE EFFECTS  Schedules the pg_cron job 'job_web_lifecycle_sweep' (every minute). Exactly one HTTP POST per run. Writes nothing:
--                 the Python sweep owns every claim and update.
-- HOW IT FITS   The only code that cancels held web payments: restaurant decline, no rider and late payment queue a
--                 web_payment_release row (lifecycle.queue_release() / reject_late()); this job (every minute) -> app_hook_post
--                 -> /web-hooks/lifecycle-sweep -> web_ordering/lifecycle.sweep() claims up to ten due rows (SKIP LOCKED,
--                 one-minute lease) and cancels each payment. The same sweep expires WEB threads (web_session_meta) and
--                 prunes web_rate_limit and status-only order_access_grant rows. If this job stops, held payments stay held.
-- LIFECYCLE     none: this job keeps no state. Release row states: ordering/web_payment_release.sql.
-- CALLED BY     job_web_lifecycle_sweep:
--                 cron      'job_web_lifecycle_sweep' * * * * *
-- PYTHON MODEL  watomation/routers/sweep_hooks.py: web_lifecycle_sweep(); utils_common/web_ordering/lifecycle.py: sweep(), release()
-- SECURITY      PUBLIC, anon and authenticated revoked; service role only.
-- TESTS         tests/sql/test_customer_sweep_jobs_sql.py
--               tests/watomation/routers/test_sweep_hooks.py
-- GOTCHAS       Option B (ADR 0019 exception, docs/to-do.md "Customer notifier sweeps"): POSTs every minute even when nothing
--                 is due, because the Python sweep also does work no SQL count can see:
--                 WEB thread expiry and the counter and grant prunes.
--                 A-lite / A in docs/to-do.md move that work to SQL so the job can POST only when due.
--               Status handling: see the app_hook_post.sql GOTCHAS (keep the result in a variable).
-- SEE ALSO      docs/adr/0019-scheduled-work-is-owned-by-pg-cron.md
--               docs/to-do.md
--               ordering/web_payment_release.sql
--               docs/web-ordering-playground.md
--               ordering/web_session_meta.sql
--               ordering/web_rate_limit.sql
--               ordering/order_access_grant.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function job_web_lifecycle_sweep() -> boolean
--   Wake the web lifecycle sweep: POST {event_type: 'web_lifecycle_sweep'} to /web-hooks/lifecycle-sweep through
--   app_hook_post() on every run, due releases or not (option B). The sweep claims release rows itself.
--   Returns true when the app answered 2xx; false on any other status or when the call failed (app_hook_post never
--   raises and returns NULL on failure). The route answers at once and runs the sweep in BackgroundTasks, so true means
--   "the app accepted the wake-up", not "the sweep succeeded".
--   Data: reads and writes nothing itself. HTTP: POST {ORDELO_APP_URL}/web-hooks/lifecycle-sweep with {"event_type": "web_lifecycle_sweep"}.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_web_lifecycle_sweep ()
    RETURNS boolean
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_status integer;
BEGIN
    -- see app_hook_post.sql GOTCHAS
    v_status := public.app_hook_post('/web-hooks/lifecycle-sweep',
        jsonb_build_object('event_type', 'web_lifecycle_sweep'));
    RETURN coalesce(v_status BETWEEN 200 AND 299, FALSE);
END;
$$;

REVOKE ALL ON FUNCTION public.job_web_lifecycle_sweep () FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.job_web_lifecycle_sweep () TO service_role;
COMMENT ON FUNCTION public.job_web_lifecycle_sweep () IS 'Every minute: POST /web-hooks/lifecycle-sweep (WEB expiry, prunes and the only release of held web payments).';

-- pg_cron job 'job_web_lifecycle_sweep': runs every minute, active on live.
SELECT cron.schedule('job_web_lifecycle_sweep', '* * * * *', 'SELECT public.job_web_lifecycle_sweep()');
-- To stop:    SELECT cron.unschedule('job_web_lifecycle_sweep');
-- To inspect: SELECT status, start_time, return_message FROM cron.job_run_details
--             WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'job_web_lifecycle_sweep') ORDER BY start_time DESC LIMIT 10;
