-- =============================================================================================
-- ordelo_datamodels/availability/job_pause_sweep.sql
-- Target every minute: close expired pauses and ask the app to send "your break ends soon" and "you're back on".
-- =============================================================================================
-- LIVE CHECK    job_pause_sweep() matches the live function on 2026-10-22. The pg_cron job is scheduled every minute
--               (* * * * *; the owner applied this file 2026-10-23, after deploying /pause-hooks/sweep).
-- OBJECTS       fn     job_pause_sweep() -> boolean
--                   Close expired pauses, then POST the due "ends soon" and "back on" messages; mark them only on a 2xx reply.
-- REQUIRES      availability/pauses.sql
--               core/ordelo_config.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Schedules the pg_cron job 'job_pause_sweep' (every minute). Each run may POST to <ORDELO_APP_URL>/pause-hooks/sweep.
-- HOW IT FITS   ADR 0013. The sweep never decides availability (is_paused() does, from the clock); it only:
--                 1. CLOSE:   open rows whose ends_at passed -> ended_at = ends_at, end_reason = 'expired' (bookkeeping only).
--                 2. REMIND:  open rows ending within PAUSE_REMIND_BEFORE_MINS, not yet reminded   -> payload "ending_soon".
--                 3. ANNOUNCE: rows closed as 'expired' in the last 24 h whose announced_at is NULL  -> payload "ended".
--                 4. POST {event_type: 'pause_sweep', ending_soon: [...], ended: [...]} to /pause-hooks/sweep; on 2xx set
--                    reminded_at / announced_at for exactly the pause_ids handed to the app. A failed POST leaves them for the next
--                    scheduled run. A later background send failure is logged but not retried; availability remains clock-derived.
--                 Each item: {pause_id, audience, principal, scope, ends_at}. The app routes by audience: 'rider' ->
--                 RiderMessenger.for_rider(principal) (ordelo/rider_messaging/: the rider's channel), 'rest_admin' -> the
--                 restaurant bot, in the admin's own chats for that restaurant (t_admin_pause_chats(), telegram/t_admin_pauses.sql).
--                 Python: watomation/routers/pause_hooks.py <- POST /pause-hooks/sweep (answers 200 at once and sends in the
--                 background, like the order-alerts route: a send that fails after the 2xx is logged, not retried).
-- LIFECYCLE     none (the pause lifecycle is in availability/pauses.sql)
-- CALLED BY     job_pause_sweep:
--                 cron      'job_pause_sweep' * * * * * (applied 2026-10-23)
-- PYTHON MODEL  none
-- SECURITY      job_pause_sweep(): REVOKE ALL FROM PUBLIC, anon, authenticated (pg_cron runs it as the owner).
-- TESTS         tests/sql/test_pauses_sql.py
--               tests/watomation/routers/test_pause_hooks.py
-- GOTCHAS       The 24-hour window on ANNOUNCE stops a backlog of stale "you're back on" messages after a long outage.
--               ORDELO_APP_URL is shared by test and local runs (see the restaurant plan's known limits): point it at the
--                 instance that should send the messages.
-- SEE ALSO      availability/pauses.sql
--               telegram/t_order_alerts.sql (same POST-then-mark pattern)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function job_pause_sweep() -> boolean
--   Close expired pauses, then POST the due "ends soon" and "back on" messages; mark them only on a 2xx reply.
--   Returns false when the POST failed (nothing marked), true otherwise (including "nothing to send").
--   Data: reads ordelo_config; reads/writes pauses.
--   HTTP: POST /pause-hooks/sweep -> watomation/routers/pause_hooks.py::pause_sweep
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_pause_sweep ()
    RETURNS boolean
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_remind interval;
    v_soon jsonb;
    v_ended jsonb;
    v_soon_ids bigint[];
    v_ended_ids bigint[];
    v_app_url text;
    v_resp http_response;
BEGIN
    -- ---- 1. CLOSE ---------------------------------------------------------------------------------------
    UPDATE
        pauses
    SET
        ended_at = ends_at,
        end_reason = 'expired'
    WHERE
        ended_at IS NULL
        AND ends_at <= now();
    -- ---- 2. REMIND --------------------------------------------------------------------------------------
    SELECT
        make_interval(mins => coalesce(nullif(btrim(config_value), '')::int, 60)) INTO v_remind
    FROM
        ordelo_config
    WHERE
        config_key = 'PAUSE_REMIND_BEFORE_MINS';
    v_remind := coalesce(v_remind, interval '60 minutes');
    SELECT
        jsonb_agg(jsonb_build_object('pause_id', p.pause_id, 'audience', p.audience, 'principal', p.principal, 'scope', p.scope, 'ends_at', p.ends_at) ORDER BY p.ends_at),
        array_agg(p.pause_id) INTO v_soon,
        v_soon_ids
    FROM
        pauses p
    WHERE
        p.ended_at IS NULL
        AND p.reminded_at IS NULL
        AND now() < p.ends_at
        AND p.ends_at <= now() + v_remind;
    -- ---- 3. ANNOUNCE ------------------------------------------------------------------------------------
    SELECT
        jsonb_agg(jsonb_build_object('pause_id', p.pause_id, 'audience', p.audience, 'principal', p.principal, 'scope', p.scope, 'ends_at', p.ends_at) ORDER BY p.ended_at),
        array_agg(p.pause_id) INTO v_ended,
        v_ended_ids
    FROM
        pauses p
    WHERE
        p.end_reason = 'expired'
        AND p.announced_at IS NULL
        AND p.ended_at > now() - interval '24 hours';
    IF v_soon IS NULL AND v_ended IS NULL THEN
        RETURN TRUE;
        -- nothing to say: the endpoint is not called at all
    END IF;
    -- ---- 4. POST, then MARK only on 2xx -------------------------------------------------------------------
    SELECT
        config_value INTO v_app_url
    FROM
        ordelo_config
    WHERE
        config_key = 'ORDELO_APP_URL';
    IF v_app_url IS NULL OR length(v_app_url) = 0 THEN
        v_app_url := 'https://agent.ordelo.app';
    END IF;
    v_app_url := rtrim(v_app_url, '/');
    SELECT
        * INTO v_resp
    FROM
        http_post (v_app_url || '/pause-hooks/sweep', jsonb_build_object('event_type', 'pause_sweep', 'ending_soon', coalesce(v_soon, '[]'::jsonb), 'ended', coalesce(v_ended, '[]'::jsonb))::text, 'application/json');
    IF v_resp.status IS NULL OR v_resp.status < 200 OR v_resp.status > 299 THEN
        RAISE NOTICE 'job_pause_sweep: POST returned %, nothing marked', v_resp.status;
        RETURN FALSE;
    END IF;
    UPDATE
        pauses
    SET
        reminded_at = now()
    WHERE
        pause_id = ANY (coalesce(v_soon_ids, '{}'));
    UPDATE
        pauses
    SET
        announced_at = now()
    WHERE
        pause_id = ANY (coalesce(v_ended_ids, '{}'));
    RETURN TRUE;
END
$$;

REVOKE ALL ON FUNCTION public.job_pause_sweep () FROM PUBLIC, anon, authenticated;

-- pg_cron job 'job_pause_sweep': every minute (applied 2026-10-23; it was */5 before).
-- cron.schedule() with an existing job name updates that job in place, so re-running is safe.
SELECT
    cron.schedule ('job_pause_sweep', '* * * * *', 'SELECT public.job_pause_sweep()');

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.job_pause_sweep () IS 'Close expired pauses, then POST the due ends-soon and back-on messages; mark them only on a 2xx reply.';

-- ---------------------------------------------------------------------------------------------
-- OPERATOR SQL (commented out on purpose)
-- ---------------------------------------------------------------------------------------------
-- Switch the sweep off:  SELECT cron.unschedule('job_pause_sweep');
-- Run it once by hand:   SELECT public.job_pause_sweep();
