-- =============================================================================================
-- ordelo_datamodels/telegram/job_rider_invite_alerts.sql
-- Every minute: wake OrdeloAgent when a rider invite claim alert is due (ADR 0019).
-- =============================================================================================
-- LIVE CHECK    not applied yet (plans/telegram-rider-invite-alert-schedule.md).
-- OBJECTS       fn     job_rider_invite_alerts() -> boolean
--                   POST /rider-hooks/invite-alerts when any rider alert is due; true when idle or answered 2xx.
-- REQUIRES      telegram/t_invites.sql (rider alert columns, t_invites_rider_alert_due_idx)
--               telegram/t_rider_invites.sql
--               platform/app_hook_post.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run (cron.schedule with an existing name updates in place).
-- SIDE EFFECTS  Schedules the pg_cron job 'job_rider_invite_alerts' (every minute). At most one HTTP POST per run, only when
--                 something is due. Writes nothing: take/finish own the state.
-- HOW IT FITS   t_rider_invite_claim sets rider_alert_next_at -> this job (every minute) -> app_hook_post -> /rider-hooks/invite-alerts
--                 -> invite_alerts.sweep_pending() -> t_rider_invite_alert_take / _finish. A failed POST changes nothing.
-- LIFECYCLE     see telegram/t_rider_invites.sql
-- CALLED BY     job_rider_invite_alerts:
--                 cron      'job_rider_invite_alerts' * * * * *
-- PYTHON MODEL  watomation/routers/sweep_hooks.py: rider_invite_alerts(); channels/telegram/rider/invite_alerts.py: sweep_pending()
-- SECURITY      PUBLIC, anon and authenticated revoked; service role only.
-- TESTS         tests/sql/test_rider_invites_sql.py
-- GOTCHAS       A row in 'sending' is not due until its lease expires (2 min), so a slow sweep is not woken twice for it.
--               The count reads due rider rows only; it never selects invite_code.
-- SEE ALSO      docs/adr/0019-scheduled-work-is-owned-by-pg-cron.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function job_rider_invite_alerts() -> boolean
--   Count the rider invite alerts that are due (t_invites.rider_alert_next_at <= now()). None due: return true without any
--   HTTP call. Otherwise POST {event_type: 'rider_invite_alerts', due} to /rider-hooks/invite-alerts through app_hook_post()
--   and return whether the app answered 2xx. The hook claims rows itself (t_rider_invite_alert_take, lease + SKIP LOCKED),
--   so this job only wakes it and writes nothing.
--   Data: reads t_invites. HTTP: POST {ORDELO_APP_URL}/rider-hooks/invite-alerts (only when due).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_rider_invite_alerts ()
    RETURNS boolean
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_due integer;
BEGIN
    SELECT count(*) INTO v_due
    FROM public.t_invites
    WHERE bot_key = 'rider' AND rider_alert_next_at <= now();   -- t_invites_rider_alert_due_idx
    IF v_due = 0 THEN
        RETURN TRUE;                                               -- nothing due: the app is not called
    END IF;
    RETURN coalesce(public.app_hook_post('/rider-hooks/invite-alerts',
        jsonb_build_object('event_type', 'rider_invite_alerts', 'due', v_due)) BETWEEN 200 AND 299, FALSE);
END;
$$;

REVOKE ALL ON FUNCTION public.job_rider_invite_alerts () FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.job_rider_invite_alerts () TO service_role;
COMMENT ON FUNCTION public.job_rider_invite_alerts () IS 'Every minute: POST /rider-hooks/invite-alerts when any rider invite claim alert is due.';

-- pg_cron job 'job_rider_invite_alerts': runs every minute, INACTIVE on live until the owner applies this file (plan P1-1).
SELECT cron.schedule('job_rider_invite_alerts', '* * * * *', 'SELECT public.job_rider_invite_alerts()');
-- To stop:    SELECT cron.unschedule('job_rider_invite_alerts');
-- To inspect: SELECT status, start_time, return_message FROM cron.job_run_details
--             WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'job_rider_invite_alerts') ORDER BY start_time DESC LIMIT 10;
