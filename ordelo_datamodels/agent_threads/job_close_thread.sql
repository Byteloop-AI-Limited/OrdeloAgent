-- =============================================================================================
-- ordelo_datamodels/agent_threads/job_close_thread.sql
-- Find OrdeloAgent threads idle longer than THREAD_INACTIVE_TIME_INTERVAL and ask the app to close them.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     job_close_thread() -> boolean
--                   POST idle active threads to /delivery-hooks/close-threads; returns whether it posted.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Each call may POST to /delivery-hooks/close-threads.
-- HOW IT FITS   Agent threads (the LangGraph conversation per WhatsApp user and agent):
--                 thread (owned by restaurant-agents) maps (recipient, agent) to a LangGraph thread_id; the checkpoint tables are
--                 written by LangGraph's AsyncPostgresSaver. OrdeloAgent reads the latest state for debugging and closes idle threads:
--                   job_close_thread()                       idle OrdeloAgent threads -> POST /delivery-hooks/close-threads
--                   job_terminate_stale_active_threads_new() idle restaurant threads  -> POST <REST>_APP_URL/thread-hooks/<rest>/terminate-stale-active-threads
--                                                            (restaurant-agents), per restaurant, every minute
--                   get_latest_state(_by_thread)()           read a thread's latest checkpoint as JSON (debug endpoints, rider agent)
--                 job_close_thread(): active threads whose last_access_dtts is older than ordelo_config THREAD_INACTIVE_TIME_INTERVAL
--                 minutes (default 5) -> POST /delivery-hooks/close-threads. Called from Python (delivery_hooks.py), not by pg_cron.
--               Rider dispatch threads (ORDELO-dispatch-<id>, since R2 of plans/telegram-rider-bot-plan.md) are in the same payload;
--                 close_threads() closes exactly that thread (rider_thread_close, agent_threads/rider_threads.sql) whether or not a
--                 cancel reason was given, and says goodbye on the job's channel (WhatsApp or Telegram). Other threads close as before.
-- LIFECYCLE     none
-- CALLED BY     job_close_thread:
--                 python    watomation/routers/delivery_hooks.py: close_threads()
-- PYTHON MODEL  none
-- SECURITY      job_close_thread(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       The body was taken from live on 2026-10-16 (the previous agent_threads copy differed; the migrations/ordelo_agg_r3.sql copy matched).
-- SEE ALSO      agent_threads/job_terminate_stale_active_threads.sql
--               agent_threads/rider_threads.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function job_close_thread() -> boolean
--   POST idle active threads to /delivery-hooks/close-threads; returns whether it posted.
--   Data: reads ordelo_config, thread.
--   HTTP: POST /delivery-hooks/close-threads -> watomation/routers/delivery_hooks.py::close_threads
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_close_thread ()
    RETURNS boolean
    LANGUAGE plpgsql
    AS $function$
DECLARE
    interval_minutes int;
    interval_expr interval;
    webhook_payload json;
    response json;
    notified boolean := FALSE;
    ordelo_app_url text;
    webhook_url text;
BEGIN
    -- Get the interval in minutes from config
    SELECT
        config_value::int INTO interval_minutes
    FROM
        ordelo_config
    WHERE
        config_key = 'THREAD_INACTIVE_TIME_INTERVAL';
    IF interval_minutes IS NULL THEN
        interval_minutes := 5;
        -- Default fallback (5 minutes)
    END IF;
    interval_expr := (interval_minutes || ' minutes')::interval;
    -- Get the base app URL from config
    SELECT
        config_value INTO ordelo_app_url
    FROM
        ordelo_config
    WHERE
        config_key = 'ORDELO_APP_URL';
    IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
        ordelo_app_url := 'https://rider-agent.ordelo.app';
        -- Fallback default
    END IF;
    webhook_url := ordelo_app_url || '/delivery-hooks/close-threads';

    WITH threads_to_close AS (
        SELECT
            thread_id,
            recipient,
            last_access_dtts,
            is_active,
            EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - last_access_dtts)) / 60 AS minutes_since_last_access
        FROM
            thread
        WHERE
            last_access_dtts IS NOT NULL
            AND CURRENT_TIMESTAMP - last_access_dtts > interval_expr
            AND retain_thread = FALSE
            AND is_active = TRUE
            AND recipient IS NOT NULL
            AND agent IS DISTINCT FROM 'WEB'
)
    SELECT
        json_agg(json_build_object('thread_id', thread_id, 'recipient', recipient, 'last_access_dtts', last_access_dtts, 'is_active', is_active, 'minutes_since_last_access', minutes_since_last_access)) INTO webhook_payload
    FROM
        threads_to_close;
    -- Only POST if there is at least one thread to close
    IF webhook_payload IS NOT NULL THEN
        response := (
            SELECT
                content
            FROM
                http_post (webhook_url, webhook_payload::text, 'application/json'));
        RAISE NOTICE 'Response from close-threads: %', response;
        notified := TRUE;
    ELSE
        RAISE NOTICE 'No threads to close.';
        notified := FALSE;
    END IF;
    RETURN notified;
END;
$function$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.job_close_thread () IS 'POST idle active threads to /delivery-hooks/close-threads; returns whether it posted.';

-- Usage:
-- select job_close_thread();
