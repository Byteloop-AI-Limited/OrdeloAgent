-- =============================================================================================
-- ordelo_datamodels/notifications/job_customer_outbox_sweep.sql
-- Every minute: wake OrdeloAgent to repair and recover the customer notification outbox (ADR 0019, option B).
-- =============================================================================================
-- LIVE CHECK    not applied yet (plans/telegram-rider-invite-alert-schedule.md, phase 2).
-- OBJECTS       fn     job_customer_outbox_sweep() -> boolean
--                   POST /customer-hooks/outbox-sweep every run; true when the app answered 2xx.
-- REQUIRES      platform/app_hook_post.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run (cron.schedule with an existing name updates in place).
-- SIDE EFFECTS  Schedules the pg_cron job 'job_customer_outbox_sweep' (every minute). Exactly one HTTP POST per run. Writes nothing:
--                 the Python sweep owns every claim and update.
-- HOW IT FITS   this job (every minute) -> app_hook_post -> /customer-hooks/outbox-sweep -> customer_notifier.sweep_pending():
--                 seed missing order_notification_subscription and notification_outbox rows, fail interrupted attempts
--                 (no retry after an HTTP attempt, ADR 0006), then dispatch up to 100 unattempted due rows.
--                 Replaces the in-process 60-second customer_notifier.run_sweeper loop.
-- LIFECYCLE     none: this job keeps no state. Outbox row states: notifications/notification_outbox.sql.
-- CALLED BY     job_customer_outbox_sweep:
--                 cron      'job_customer_outbox_sweep' * * * * *
-- PYTHON MODEL  watomation/routers/sweep_hooks.py: customer_outbox_sweep(); utils_common/notify/customer_notifier.py: sweep_pending()
-- SECURITY      PUBLIC, anon and authenticated revoked; service role only.
-- TESTS         tests/sql/test_customer_sweep_jobs_sql.py
--               tests/watomation/routers/test_sweep_hooks.py
-- GOTCHAS       Option B (ADR 0019 exception, docs/to-do.md "Customer notifier sweeps"): POSTs every minute even when nothing
--                 is due, because the Python sweep also does work no SQL count can see:
--                 subscription and outbox seeding, interrupted-attempt failure.
--                 A-lite / A in docs/to-do.md move that work to SQL so the job can POST only when due.
--               Status handling: see the app_hook_post.sql GOTCHAS (keep the result in a variable).
-- SEE ALSO      docs/adr/0019-scheduled-work-is-owned-by-pg-cron.md
--               docs/to-do.md
--               notifications/notification_outbox.sql
--               notifications/order_notification_subscription.sql
--               notifications/order_customer_event.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function job_customer_outbox_sweep() -> boolean
--   Wake the customer outbox sweep: POST {event_type: 'customer_outbox_sweep'} to /customer-hooks/outbox-sweep through
--   app_hook_post() on every run, due rows or not (option B). The sweep claims each outbox row before any I/O.
--   Returns true when the app answered 2xx; false on any other status or when the call failed (app_hook_post never
--   raises and returns NULL on failure). The route answers at once and runs the sweep in BackgroundTasks, so true means
--   "the app accepted the wake-up", not "the sweep succeeded".
--   Data: reads and writes nothing itself. HTTP: POST {ORDELO_APP_URL}/customer-hooks/outbox-sweep with {"event_type": "customer_outbox_sweep"}.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_customer_outbox_sweep ()
    RETURNS boolean
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_status integer;
BEGIN
    -- see app_hook_post.sql GOTCHAS
    v_status := public.app_hook_post('/customer-hooks/outbox-sweep',
        jsonb_build_object('event_type', 'customer_outbox_sweep'));
    RETURN coalesce(v_status BETWEEN 200 AND 299, FALSE);
END;
$$;

REVOKE ALL ON FUNCTION public.job_customer_outbox_sweep () FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.job_customer_outbox_sweep () TO service_role;
COMMENT ON FUNCTION public.job_customer_outbox_sweep () IS 'Every minute: POST /customer-hooks/outbox-sweep (customer outbox repair and recovery, option B).';

-- pg_cron job 'job_customer_outbox_sweep': runs every minute, INACTIVE on live until the owner applies this file (plan phase 2).
SELECT cron.schedule('job_customer_outbox_sweep', '* * * * *', 'SELECT public.job_customer_outbox_sweep()');
-- To stop:    SELECT cron.unschedule('job_customer_outbox_sweep');
-- To inspect: SELECT status, start_time, return_message FROM cron.job_run_details
--             WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'job_customer_outbox_sweep') ORDER BY start_time DESC LIMIT 10;
