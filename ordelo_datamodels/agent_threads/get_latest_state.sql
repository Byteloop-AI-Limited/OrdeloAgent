-- =============================================================================================
-- ordelo_datamodels/agent_threads/get_latest_state.sql
-- Read the latest LangGraph checkpoint of a thread (or of a recipient's active thread) as JSON.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     get_latest_state_by_thread(p_thread_id text, p_state_key text) -> jsonb
--                   Return the latest root checkpoint of a thread as jsonb (checkpoint ids, channel values), or one state key.
--               fn     get_latest_state(p_recipient character varying, p_agent text, p_state_key text) -> jsonb
--                   Return the latest state of the active thread for (recipient, agent), plus thread metadata; NULL when none.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none (read-only functions)
-- HOW IT FITS   Agent threads (the LangGraph conversation per WhatsApp user and agent):
--                 thread (owned by restaurant-agents) maps (recipient, agent) to a LangGraph thread_id; the checkpoint tables are
--                 written by LangGraph's AsyncPostgresSaver. OrdeloAgent reads the latest state for debugging and closes idle threads:
--                   job_close_thread()                       idle OrdeloAgent threads -> POST /delivery-hooks/close-threads
--                   job_terminate_stale_active_threads_new() idle restaurant threads  -> POST <REST>_APP_URL/thread-hooks/<rest>/terminate-stale-active-threads
--                                                            (restaurant-agents), per restaurant, every minute
--                   get_latest_state(_by_thread)()           read a thread's latest checkpoint as JSON (debug endpoints, rider agent)
-- LIFECYCLE     none
-- CALLED BY     get_latest_state_by_thread:
--                 sql       get_latest_state() (agent_threads/get_latest_state.sql)
--               get_latest_state:
--                 python    ordelo/agents/agent_runner.py: is_food_already_picked_up()
-- PYTHON MODEL  none
-- SECURITY      get_latest_state_by_thread(): executable by PUBLIC (default)
--               get_latest_state(): executable by PUBLIC (default)
-- TESTS         tests/ordelo/agents/test_agent_runner.py
-- GOTCHAS       none
-- SEE ALSO      docs/get_latest_state_guide.md
--               agent_threads/job_close_thread.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function get_latest_state_by_thread(p_thread_id text, p_state_key text) -> jsonb
--   Return the latest root checkpoint of a thread as jsonb (checkpoint ids, channel values), or one state key.
--   Reads checkpoints / checkpoint_blobs written by LangGraph; NULL when the thread has no checkpoint.
--   Data: reads checkpoint_blobs, checkpoints.
-- ---------------------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS get_latest_state_by_thread (TEXT, TEXT);

CREATE OR REPLACE FUNCTION get_latest_state_by_thread (p_thread_id text, p_state_key text DEFAULT NULL)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    AS $$
DECLARE
    v_checkpoint_id text;
    v_parent_checkpoint_id text;
    v_checkpoint jsonb;
    v_state jsonb;
    v_blob_channels jsonb;
BEGIN
    IF p_thread_id IS NULL OR btrim(p_thread_id) = '' THEN
        RETURN NULL;
    END IF;
    -- Latest root checkpoint for the thread; sub-graph namespaces are skipped
    SELECT
        c.checkpoint_id,
        c.parent_checkpoint_id,
        c.checkpoint INTO v_checkpoint_id,
        v_parent_checkpoint_id,
        v_checkpoint
    FROM
        public.checkpoints AS c
    WHERE
        c.thread_id = p_thread_id
        AND c.checkpoint_ns = ''
    ORDER BY
        c.checkpoint_id DESC
    LIMIT 1;

    IF v_checkpoint_id IS NULL THEN
        RETURN NULL;
    END IF;
    -- Inline primitives are the only SQL-readable state values
    v_state := COALESCE(v_checkpoint -> 'channel_values', '{}'::jsonb);

    IF p_state_key IS NOT NULL THEN
        RETURN v_state -> p_state_key;
    END IF;
    -- Channels held in checkpoint_blobs (msgpack) surface as metadata, not values
    SELECT
        COALESCE(jsonb_agg(jsonb_build_object('channel', b.channel, 'type', b.type, 'size_bytes', octet_length(b.blob))
            ORDER BY b.channel), '[]'::jsonb) INTO v_blob_channels
    FROM
        jsonb_each_text(COALESCE(v_checkpoint -> 'channel_versions', '{}'::jsonb)) AS cv (channel,
        version)
    JOIN public.checkpoint_blobs AS b ON b.thread_id = p_thread_id
        AND b.checkpoint_ns = ''
        AND b.channel = cv.channel
        AND b.version = cv.version
WHERE
    b.type <> 'empty';

    RETURN jsonb_build_object('thread_id', p_thread_id, 'checkpoint_ns', '', 'checkpoint_id', v_checkpoint_id, 'parent_checkpoint_id', v_parent_checkpoint_id, 'checkpoint_ts', v_checkpoint ->> 'ts', 'state', v_state, 'blob_channels', v_blob_channels);
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- function get_latest_state(p_recipient character varying, p_agent text, p_state_key text) -> jsonb
--   Return the latest state of the active thread for (recipient, agent), plus thread metadata; NULL when none.
--   Data: reads thread; calls get_latest_state_by_thread().
-- ---------------------------------------------------------------------------------------------
DROP FUNCTION IF EXISTS get_latest_state (VARCHAR, TEXT, TEXT);

CREATE OR REPLACE FUNCTION get_latest_state (p_recipient varchar, p_agent text DEFAULT NULL, p_state_key text DEFAULT NULL)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    AS $$
DECLARE
    v_thread RECORD;
    v_result jsonb;
BEGIN
    IF p_recipient IS NULL OR btrim(p_recipient) = '' THEN
        RETURN NULL;
    END IF;
    -- Newest active thread for the recipient; no last_access_dtts side effect
    SELECT
        t.thread_id,
        t.agent,
        t.recipient,
        t.retain_thread,
        t.dtts,
        t.last_access_dtts INTO v_thread
    FROM
        public.thread AS t
    WHERE
        t.recipient = p_recipient
        AND t.is_active IS TRUE
        AND (p_agent IS NULL
            OR t.agent IS NULL
            OR upper(t.agent) = upper(p_agent))
    ORDER BY
        t.dtts DESC,
        t.last_access_dtts DESC
    LIMIT 1;

    IF v_thread.thread_id IS NULL THEN
        RETURN NULL;
    END IF;

    v_result := get_latest_state_by_thread (v_thread.thread_id, p_state_key);
    -- Single-key lookups stay bare so callers can compare directly
    IF p_state_key IS NOT NULL OR v_result IS NULL THEN
        RETURN v_result;
    END IF;

    RETURN v_result || jsonb_build_object('agent', v_thread.agent, 'recipient', v_thread.recipient, 'thread_retain_thread', v_thread.retain_thread, 'thread_dtts', v_thread.dtts, 'thread_last_access_dtts', v_thread.last_access_dtts);
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.get_latest_state_by_thread (p_thread_id text, p_state_key text) IS 'Return the latest root checkpoint of a thread as jsonb (checkpoint ids, channel values), or one state key.';

COMMENT ON FUNCTION public.get_latest_state (p_recipient character varying, p_agent text, p_state_key text) IS 'Return the latest state of the active thread for (recipient, agent), plus thread metadata; NULL when none.';

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- Usage:
-- Full state envelope for the rider's active thread
-- SELECT get_latest_state('447700900123', 'ELAS');
--
-- Any agent (latest active thread wins)
-- SELECT get_latest_state('447700900123');
--
-- Single value, bare JSONB (NULL when absent or msgpack-backed)
-- SELECT get_latest_state('447700900123', 'ELAS', 'order_number') #>> '{}' AS order_number;
-- SELECT (get_latest_state('447700900123', 'ELAS', 'retain_thread') = 'true'::jsonb) IS TRUE AS is_retained;
--
-- Straight from thread_id
-- SELECT get_latest_state_by_thread('ELAS-6e9d53c8-d17c-4015-899e-1d446fdd05f9');
-- SELECT get_latest_state_by_thread('ELAS-6e9d53c8-d17c-4015-899e-1d446fdd05f9', 'dispatch_id');
--
-- Supabase REST RPC
-- client_ordelo.rpc("get_latest_state", {"p_recipient": "447700900123", "p_agent": "ELAS"}).execute()


----------------------------- DEBUG QUERY -----------------------------

-- 1. Every active thread with its resolvable state, to see who has no checkpoint yet.
-- SELECT
--     t.thread_id,
--     t.agent,
--     t.recipient,
--     t.last_access_dtts,
--     gs.state_env IS NOT NULL AS has_root_checkpoint,
--     gs.state_env ->> 'checkpoint_id' AS checkpoint_id,
--     gs.state_env ->> 'checkpoint_ts' AS checkpoint_ts,
--     t.retain_thread AS retain_thread,  -- thread column, not an AgentState channel; see header
--     jsonb_pretty(gs.state_env -> 'state') AS inline_state,
--     gs.state_env -> 'blob_channels' AS blob_channels
-- FROM public.thread AS t
-- LEFT JOIN LATERAL get_latest_state_by_thread(t.thread_id) AS gs(state_env) ON TRUE
-- WHERE t.is_active IS TRUE
-- ORDER BY t.last_access_dtts DESC;

-- 2. Which state keys are SQL-readable (inline) vs msgpack-only, for one thread.
-- WITH latest AS (
--     SELECT get_latest_state_by_thread(
--         'ELAS-6e9d53c8-d17c-4015-899e-1d446fdd05f9'  -- replace with the thread_id to inspect
--     ) AS state_env
-- )
-- SELECT
--     'inline' AS storage,
--     kv.key AS channel,
--     kv.value AS value
-- FROM latest
-- CROSS JOIN jsonb_each(latest.state_env -> 'state') AS kv
-- UNION ALL
-- SELECT
--     'blob' AS storage,
--     bc.value ->> 'channel' AS channel,
--     bc.value - 'channel' AS value
-- FROM latest
-- CROSS JOIN jsonb_array_elements(latest.state_env -> 'blob_channels') AS bc
-- ORDER BY storage, channel;

-- 3. Confirm both functions are deployed with the expected signatures.
-- SELECT
--     p.oid::regprocedure::text AS function_signature,
--     pg_get_function_result(p.oid) AS return_type,
--     p.provolatile AS volatility
-- FROM pg_proc AS p
-- JOIN pg_namespace AS n
--   ON n.oid = p.pronamespace
-- WHERE n.nspname = 'public'
--   AND p.proname IN ('get_latest_state', 'get_latest_state_by_thread')
-- ORDER BY p.proname;

----------------------------- END DEBUG QUERY -----------------------------
----------------------------- TEST QUERY -----------------------------
-- select * from get_latest_state_by_thread('ELAS-c8ce70f0-83a5-420c-ab9d-268c8060f11d');

-- select * from get_latest_state('447448440754', 'ORDELO');
