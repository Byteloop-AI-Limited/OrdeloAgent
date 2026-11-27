-- =============================================================================================
-- ordelo_datamodels/platform/app_hook_post.sql
-- The one way SQL wakes OrdeloAgent: POST JSON to {ORDELO_APP_URL}<path> with a timeout (ADR 0019).
-- =============================================================================================
-- LIVE CHECK    not applied yet (plans/telegram-rider-invite-alert-schedule.md).
-- OBJECTS       fn     app_hook_post(p_path text, p_payload jsonb, p_timeout_secs integer) -> integer
--                   POST p_payload to ORDELO_APP_URL + p_path; return the HTTP status, NULL when the call failed. Never raises.
-- REQUIRES      core/ordelo_config.sql
--               extension http (pgsql-http >= 1.3, with http_set_curlopt / http_reset_curlopt)
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run. No BEGIN/COMMIT.
-- SIDE EFFECTS  One HTTP POST per call; a NOTICE when the answer is not 2xx or the call fails.
-- HOW IT FITS   pg_cron job_*() -> app_hook_post('/<area>-hooks/<name>', payload) -> thin FastAPI route -> BackgroundTasks.
--                 ORDELO_APP_URL decides which server does the work (production, or a local tunnel during tests).
-- LIFECYCLE     none
-- CALLED BY     app_hook_post:
--                 sql       job_rider_invite_alerts() (telegram/job_rider_invite_alerts.sql)
--                 sql       job_customer_outbox_sweep() (notifications/job_customer_outbox_sweep.sql)
--                 sql       job_web_lifecycle_sweep() (ordering/job_web_lifecycle_sweep.sql)
--                 sql       job_web_price_audit() (ordering/job_web_price_audit.sql)
-- PYTHON MODEL  watomation/routers/sweep_hooks.py (the routes it calls)
-- SECURITY      PUBLIC, anon and authenticated revoked; service role only.
-- TESTS         tests/sql/test_app_hook_post_sql.py
--               tests/sql/test_rider_invites_sql.py (job_rider_invite_alerts)
--               tests/sql/test_customer_sweep_jobs_sql.py (the three customer sweep jobs)
-- GOTCHAS       Falls back to https://agent.ordelo.app when ORDELO_APP_URL is empty, like the inline copies.
--               The curl timeout is reset after every call, failed ones too: curlopts are C-level session state that the
--                 EXCEPTION rollback does not undo, so a reused session (SQL editor) would keep CURLOPT_TIMEOUT and cut off
--                 later http_post calls. pg_cron opens a fresh session per run in any case.
--               Callers: keep the result in a variable before testing it ("v_status := app_hook_post(...)"). Never write
--                 "app_hook_post(...) BETWEEN 200 AND 299": BETWEEN repeats its operand, so the volatile call runs, and
--                 POSTs, twice. Every job_*() that calls this function points here instead of repeating the warning.
--               Older functions still build the hook URL inline; they move here when next edited (docs/to-do.md).
-- SEE ALSO      platform/ordelo_post.sql (operator helper, different contract)
--               docs/adr/0019-scheduled-work-is-owned-by-pg-cron.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function app_hook_post(p_path text, p_payload jsonb, p_timeout_secs integer) -> integer
--   Build ORDELO_APP_URL (trailing slash trimmed) + '/' + p_path (leading slash trimmed), POST the payload as JSON with a
--   curl timeout of p_timeout_secs (minimum 1), and return the status. Returns NULL instead of raising, so a job's own
--   bookkeeping never rolls back because the app is down. The caller decides what a non-2xx means. The curl timeout is
--   reset on both paths; the reset in the EXCEPTION handler has its own BEGIN/EXCEPTION so it cannot raise either.
--   Data: reads ordelo_config. HTTP: POST {ORDELO_APP_URL}/<p_path>.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.app_hook_post (p_path text, p_payload jsonb DEFAULT '{}'::jsonb, p_timeout_secs integer DEFAULT 5)
    RETURNS integer
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_base text;
    v_url text;
    v_resp http_response;
BEGIN
    SELECT nullif(btrim(config_value), '') INTO v_base
    FROM public.ordelo_config
    WHERE config_key = 'ORDELO_APP_URL';
    v_url := rtrim(coalesce(v_base, 'https://agent.ordelo.app'), '/') || '/' || ltrim(p_path, '/');
    PERFORM http_set_curlopt('CURLOPT_TIMEOUT', greatest(coalesce(p_timeout_secs, 5), 1)::text);
    SELECT * INTO v_resp FROM http_post(v_url, coalesce(p_payload, '{}'::jsonb)::text, 'application/json');
    PERFORM http_reset_curlopt();
    IF v_resp.status IS NULL OR v_resp.status NOT BETWEEN 200 AND 299 THEN
        RAISE NOTICE 'app_hook_post: POST % returned %', v_url, v_resp.status;
    END IF;
    RETURN v_resp.status;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'app_hook_post: POST % failed: %', v_url, SQLERRM;
        BEGIN
            PERFORM http_reset_curlopt();
        EXCEPTION
            WHEN OTHERS THEN
                NULL;
        END;
        RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION public.app_hook_post (text, jsonb, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.app_hook_post (text, jsonb, integer) TO service_role;

COMMENT ON FUNCTION public.app_hook_post (text, jsonb, integer) IS 'POST p_payload to ORDELO_APP_URL + p_path; return the HTTP status, NULL when the call failed. Never raises.';
