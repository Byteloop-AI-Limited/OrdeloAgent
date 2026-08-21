/*
Latest LangGraph state readers - expose the most recent persisted graph state as JSONB.
  Storage facts (langgraph-checkpoint-postgres 3.0.5, verified against the live DB):
    . public.checkpoints holds one row per superstep; the root graph uses checkpoint_ns = ''
      (sub-graph namespaces also exist and are deliberately ignored here)
    . primitive channel values (text / number / boolean / null) are INLINED at
      checkpoint -> 'channel_values' - this covers rider_agent AgentState fields such as
      dispatch_id, order_number, pickup_time, retain_thread, wa_location_request_id
    . non-primitive channels (messages, customer_address, dicts, models) are serialised into
      public.checkpoint_blobs as msgpack BYTEA, which SQL cannot decode; they are therefore
      reported as metadata only (channel / type / size_bytes) under 'blob_channels'
    . the latest checkpoint is the highest checkpoint_id (time-ordered UUID), matching both
      AsyncPostgresSaver.aget_tuple and job_terminate_stale_active_threads
  Behaviour:
    . p_state_key IS NULL  -> envelope {thread_id, checkpoint_id, checkpoint_ts, state, blob_channels}
    . p_state_key provided -> the bare JSONB value of that channel
      (NULL when the key is absent or is blob-backed, e.g. 'messages')
    . returns NULL when no active thread or no root checkpoint exists
    . read-only by design: unlike get_active_thread(), thread.last_access_dtts is NOT bumped,
      so reading state can never keep a stale thread alive or skew the stale-thread job
  Thread resolution (mirrors utils_common/thread_management/thread_mgmnt.sql):
    . active thread only (is_active IS TRUE), newest first (dtts DESC), one row
    . agent match is case-insensitive; p_agent NULL means "any agent"
Functions:
    . get_latest_state_by_thread - latest persisted state for a known thread_id
    . get_latest_state - resolves the latest active thread for (recipient, agent), then delegates
*/

-- %% Latest state for a known thread_id
DROP FUNCTION IF EXISTS get_latest_state_by_thread(TEXT, TEXT);
CREATE OR REPLACE FUNCTION get_latest_state_by_thread(
    p_thread_id TEXT,
    p_state_key TEXT DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_checkpoint_id TEXT;
    v_parent_checkpoint_id TEXT;
    v_checkpoint JSONB;
    v_state JSONB;
    v_blob_channels JSONB;
BEGIN
    IF p_thread_id IS NULL OR btrim(p_thread_id) = '' THEN
        RETURN NULL;
    END IF;

    -- Latest root checkpoint for the thread; sub-graph namespaces are skipped
    SELECT
        c.checkpoint_id,
        c.parent_checkpoint_id,
        c.checkpoint
    INTO
        v_checkpoint_id,
        v_parent_checkpoint_id,
        v_checkpoint
    FROM public.checkpoints AS c
    WHERE c.thread_id = p_thread_id
      AND c.checkpoint_ns = ''
    ORDER BY c.checkpoint_id DESC
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
    SELECT COALESCE(
        jsonb_agg(
            jsonb_build_object(
                'channel', b.channel,
                'type', b.type,
                'size_bytes', octet_length(b.blob)
            )
            ORDER BY b.channel
        ),
        '[]'::jsonb
    )
    INTO v_blob_channels
    FROM jsonb_each_text(
        COALESCE(v_checkpoint -> 'channel_versions', '{}'::jsonb)
    ) AS cv(channel, version)
    JOIN public.checkpoint_blobs AS b
      ON b.thread_id = p_thread_id
     AND b.checkpoint_ns = ''
     AND b.channel = cv.channel
     AND b.version = cv.version
    WHERE b.type <> 'empty';

    RETURN jsonb_build_object(
        'thread_id', p_thread_id,
        'checkpoint_ns', '',
        'checkpoint_id', v_checkpoint_id,
        'parent_checkpoint_id', v_parent_checkpoint_id,
        'checkpoint_ts', v_checkpoint ->> 'ts',
        'state', v_state,
        'blob_channels', v_blob_channels
    );
END;
$$;


-- %% Latest state for the active thread of a (recipient, agent) pair
DROP FUNCTION IF EXISTS get_latest_state(VARCHAR, TEXT, TEXT);
CREATE OR REPLACE FUNCTION get_latest_state(
    p_recipient VARCHAR,
    p_agent TEXT DEFAULT NULL,
    p_state_key TEXT DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_thread RECORD;
    v_result JSONB;
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
        t.last_access_dtts
    INTO v_thread
    FROM public.thread AS t
    WHERE t.recipient = p_recipient
      AND t.is_active IS TRUE
      AND (
          p_agent IS NULL
          OR t.agent IS NULL
          OR upper(t.agent) = upper(p_agent)
      )
    ORDER BY t.dtts DESC, t.last_access_dtts DESC
    LIMIT 1;

    IF v_thread.thread_id IS NULL THEN
        RETURN NULL;
    END IF;

    v_result := get_latest_state_by_thread(v_thread.thread_id, p_state_key);

    -- Single-key lookups stay bare so callers can compare directly
    IF p_state_key IS NOT NULL OR v_result IS NULL THEN
        RETURN v_result;
    END IF;

    RETURN v_result || jsonb_build_object(
        'agent', v_thread.agent,
        'recipient', v_thread.recipient,
        'thread_retain_thread', v_thread.retain_thread,
        'thread_dtts', v_thread.dtts,
        'thread_last_access_dtts', v_thread.last_access_dtts
    );
END;
$$;


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
SELECT
    t.thread_id,
    t.agent,
    t.recipient,
    t.last_access_dtts,
    gs.state_env IS NOT NULL AS has_root_checkpoint,
    gs.state_env ->> 'checkpoint_id' AS checkpoint_id,
    gs.state_env ->> 'checkpoint_ts' AS checkpoint_ts,
    gs.state_env -> 'state' -> 'retain_thread' AS retain_thread_state_value,
    jsonb_pretty(gs.state_env -> 'state') AS inline_state,
    gs.state_env -> 'blob_channels' AS blob_channels
FROM public.thread AS t
LEFT JOIN LATERAL get_latest_state_by_thread(t.thread_id) AS gs(state_env) ON TRUE
WHERE t.is_active IS TRUE
ORDER BY t.last_access_dtts DESC;

-- 2. Which state keys are SQL-readable (inline) vs msgpack-only, for one thread.
WITH latest AS (
    SELECT get_latest_state_by_thread(
        'ELAS-6e9d53c8-d17c-4015-899e-1d446fdd05f9'  -- replace with the thread_id to inspect
    ) AS state_env
)
SELECT
    'inline' AS storage,
    kv.key AS channel,
    kv.value AS value
FROM latest
CROSS JOIN jsonb_each(latest.state_env -> 'state') AS kv
UNION ALL
SELECT
    'blob' AS storage,
    bc.value ->> 'channel' AS channel,
    bc.value - 'channel' AS value
FROM latest
CROSS JOIN jsonb_array_elements(latest.state_env -> 'blob_channels') AS bc
ORDER BY storage, channel;

-- 3. Confirm both functions are deployed with the expected signatures.
SELECT
    p.oid::regprocedure::text AS function_signature,
    pg_get_function_result(p.oid) AS return_type,
    p.provolatile AS volatility
FROM pg_proc AS p
JOIN pg_namespace AS n
  ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.proname IN ('get_latest_state', 'get_latest_state_by_thread')
ORDER BY p.proname;
----------------------------- END DEBUG QUERY -----------------------------
