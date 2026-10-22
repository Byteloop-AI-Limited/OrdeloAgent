-- =============================================================================================
-- ordelo_datamodels/agent_threads/rider_threads.sql
-- Rider agent threads, one per assigned dispatch: open, touch, find, close (the shared thread table is not changed).
-- =============================================================================================
-- LIVE CHECK    Live since 2026-10-22 (migrations/rider_telegram_r2_r4.sql step 3; ADR 0012 Amendment 1); tested live with a rider job.
-- OBJECTS       fn     rider_thread_id(p_agent text, p_dispatch_id bigint) -> text
--                   The thread id of a dispatch: '<agent>-dispatch-<dispatch_id>' (e.g. ORDELO-dispatch-84217).
--               fn     rider_thread_open(p_agent text, p_rider_id text, p_dispatch_id bigint) -> jsonb
--                   Open the thread of an assigned dispatch (idempotent) and close the rider's other rider threads (D47).
--               fn     rider_thread_touch(p_thread_id text) -> jsonb
--                   Mark an open thread as just used (last_access_dtts) and return its snapshot; refuses closed threads.
--               fn     rider_thread_active(p_agent text, p_rider_id text, p_touch boolean) -> jsonb
--                   The rider's open rider thread (newest), with its dispatch and channel; optionally touches it.
--               fn     rider_thread_describe(p_thread_id text, p_dispatch_id bigint) -> jsonb
--                   Read-only snapshot of one thread, found by thread id or by dispatch id (debug, close-threads, hooks).
--               fn     rider_thread_close(p_thread_id text) -> jsonb
--                   Close exactly this thread (never every thread of the phone).
-- REQUIRES      dispatch/delivery_dispatch.sql (thread_id, channel columns)
--               core/rider_master.sql (tcid)
--               restaurant-agents: thread
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none when applied (functions only).
-- HOW IT FITS   D46 / D47 (ADR 0012 Amendment 1). The thread table belongs to restaurant-agents and is shared with customer and WEB
--                 threads; its functions (create_thread, get_or_create_thread, make_threads_inactive, ...) are NOT changed. New
--                 rider threads are ordinary rows whose id is computed from the dispatch, so the id keeps the '<agent>-<suffix>'
--                 shape that job_terminate_stale_active_threads_new() reads with split_part(thread_id, '-', 1).
--               Nothing parses the id: rider_thread_open() writes it to delivery_dispatch.thread_id, and every lookup joins
--                 thread.thread_id = delivery_dispatch.thread_id to get the dispatch, its order, its channel (D44) and the rider's
--                 Telegram chat (rider_master.tcid).
--               Flow: delivery_inflight INSERT -> /delivery-hooks/delivery-inflight-graph-init -> rider_threads.open_for_dispatch()
--                 -> rider_thread_open() 'opened' -> the graph is initialised once ('existing' -> nothing, the hook re-fired).
--                 Every run of the rider graph first calls rider_thread_touch() (or rider_thread_active() for a message that
--                 names no dispatch): a closed thread is never run and never re-created, and last_access_dtts stays fresh for the
--                 stale-thread close job (job_close_thread).
--                 Completion / termination tools close exactly their own thread (rider_thread_close()).
--               Threads that were open before R2 (ids 'ORDELO-<uuid>', no delivery_dispatch.thread_id) are still found by
--                 rider_thread_active() (dispatch fields NULL, channel 'whatsapp') and close the old way.
-- LIFECYCLE     RESULT VOCABULARY (jsonb {result, ...})
--                 rider_thread_open:     opened | existing (already open) | closed (this dispatch's thread already finished:
--                                        never reopened) | not_found (no such dispatch, or it is another rider's)
--                                        + thread_id, closed (array of the rider's other threads closed now)
--                 rider_thread_touch:    active | inactive | not_found (+ snapshot)
--                 rider_thread_active:   active | none (+ snapshot)
--                 rider_thread_describe: found | not_found (+ snapshot)
--                 rider_thread_close:    closed | not_active
--               Snapshot: thread_id, rider_id, is_active, dispatch_id, order_number, dispatch_status, channel, tcid.
--               Closing another thread on open (D47) records its missing cancel reason as 'not given (next job started)'.
-- CALLED BY     rider_thread_id:
--                 sql       rider_thread_open() (agent_threads/rider_threads.sql)
--               rider_thread_open:
--                 python    ordelo/agents/rider_threads.py: open_for_dispatch()
--               rider_thread_touch:
--                 python    ordelo/agents/rider_threads.py: touch()
--               rider_thread_active:
--                 python    ordelo/agents/rider_threads.py: active_for_rider()
--               rider_thread_describe:
--                 python    ordelo/agents/rider_threads.py: describe(), for_dispatch()
--               rider_thread_close:
--                 python    ordelo/agents/rider_threads.py: close()
-- PYTHON MODEL  ordelo/agents/rider_threads.py (RiderThread)
-- SECURITY      Every function: REVOKE ALL FROM PUBLIC, anon, authenticated; called through the psycopg pool (as ThreadHandler is).
-- TESTS         tests/sql/test_rider_threads_sql.py
--               tests/sql/test_rider_telegram_r2_r4_migration_sql.py
--               tests/sql/test_rider_telegram_jobs_script_sql.py
--               tests/ordelo/agents/test_rider_threads.py
-- GOTCHAS       thread.recipient is varchar(12): the rider_id (phone) fits; the thread is still addressed by its dispatch's channel.
--               rider_thread_open() serialises per rider with pg_advisory_xact_lock(hashtext('rider_thread:' || rider_id)), so two
--                 assignments for one rider at the same moment cannot both stay open.
--               A dispatch id is never reused (serial), so a closed dispatch thread is never reopened.
-- SEE ALSO      dispatch/delivery_dispatch.sql
--               agent_threads/job_close_thread.sql
--               docs/adr/0012-rider-threads-follow-dispatch-assignments.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function rider_thread_id(p_agent text, p_dispatch_id bigint) -> text
--   '<agent>-dispatch-<dispatch_id>'. The only place the id is built; nothing reads it back apart.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rider_thread_id (p_agent text, p_dispatch_id bigint)
    RETURNS text
    LANGUAGE sql
    IMMUTABLE
    AS $$
    SELECT
        p_agent || '-dispatch-' || p_dispatch_id::text;
$$;

REVOKE ALL ON FUNCTION public.rider_thread_id (text, bigint) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function rider_thread_describe(p_thread_id text, p_dispatch_id bigint) -> jsonb
--   Read-only snapshot by thread id, or (when p_thread_id is NULL) by the dispatch's recorded thread.
--   Data: reads thread, delivery_dispatch, rider_master.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rider_thread_describe (p_thread_id text DEFAULT NULL, p_dispatch_id bigint DEFAULT NULL)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        coalesce((
            SELECT
                jsonb_build_object('result', 'found', 'thread_id', t.thread_id, 'rider_id', t.recipient, 'is_active', coalesce(t.is_active, FALSE), 'dispatch_id', d.dispatch_id, 'order_number', d.order_number, 'dispatch_status', d.status, 'channel', coalesce(d.channel, 'whatsapp'), 'tcid', rm.tcid)
            FROM thread t
            LEFT JOIN delivery_dispatch d ON d.thread_id = t.thread_id
            LEFT JOIN rider_master rm ON rm.rider_id = t.recipient
        WHERE
            t.thread_id = coalesce(p_thread_id, (
                SELECT
                    dd.thread_id
                FROM delivery_dispatch dd
                WHERE
                    dd.dispatch_id = p_dispatch_id))
        LIMIT 1), jsonb_build_object('result', 'not_found'));
$$;

REVOKE ALL ON FUNCTION public.rider_thread_describe (text, bigint) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function rider_thread_open(p_agent text, p_rider_id text, p_dispatch_id bigint) -> jsonb
--   Called once per assignment by the inflight hook. In one transaction, serialised per rider:
--     1. the dispatch must exist and belong to p_rider_id               (else not_found)
--     2. close every OTHER open thread of this rider and agent (D47); a declined dispatch among them gets
--        reason_for_decline 'not given (next job started)' if it had none
--     3. insert the dispatch thread ON CONFLICT DO NOTHING                (opened | existing | closed)
--     4. record it on delivery_dispatch.thread_id
--   Data: reads/writes thread, delivery_dispatch.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rider_thread_open (p_agent text, p_rider_id text, p_dispatch_id bigint)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_thread text := rider_thread_id (p_agent, p_dispatch_id);
    v_closed text[];
    v_result text;
    v_active boolean;
BEGIN
    PERFORM
        pg_advisory_xact_lock(hashtext('rider_thread:' || p_rider_id));
    IF NOT EXISTS (
        SELECT
            1
        FROM
            delivery_dispatch
        WHERE
            dispatch_id = p_dispatch_id
            AND rider_id = p_rider_id) THEN
    RETURN jsonb_build_object('result', 'not_found', 'thread_id', v_thread);
END IF;
    WITH closed AS (
        UPDATE
            thread
        SET
            is_active = FALSE
        WHERE
            recipient = p_rider_id
            AND (agent = p_agent
                OR agent IS NULL)
            AND is_active IS TRUE
            AND thread_id <> v_thread
        RETURNING
            thread_id
)
    SELECT
        coalesce(array_agg(thread_id), '{}') INTO v_closed
    FROM
        closed;
    IF cardinality(v_closed) > 0 THEN
        UPDATE
            delivery_dispatch
        SET
            reason_for_decline = 'not given (next job started)',
            status_update_dtts = CURRENT_TIMESTAMP
        WHERE
            thread_id = ANY (v_closed)
            AND status = 'declined'
            AND reason_for_decline IS NULL;
    END IF;
    INSERT INTO thread (thread_id, agent, recipient, is_active, last_access_dtts)
        VALUES (v_thread, p_agent, p_rider_id, TRUE, CURRENT_TIMESTAMP)
    ON CONFLICT (thread_id)
        DO NOTHING;
    IF FOUND THEN
        v_result := 'opened';
    ELSE
        SELECT
            is_active INTO v_active
        FROM
            thread
        WHERE
            thread_id = v_thread;
        v_result := CASE WHEN v_active THEN
            'existing'
        ELSE
            'closed'
        END;
    END IF;
    UPDATE
        delivery_dispatch
    SET
        thread_id = v_thread
    WHERE
        dispatch_id = p_dispatch_id
        AND thread_id IS DISTINCT FROM v_thread;
    RETURN jsonb_build_object('result', v_result, 'thread_id', v_thread, 'closed', to_jsonb(v_closed));
END;
$$;

REVOKE ALL ON FUNCTION public.rider_thread_open (text, text, bigint) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function rider_thread_touch(p_thread_id text) -> jsonb
--   Before every graph run: last_access_dtts = now() on an OPEN thread and its snapshot (result 'active').
--   A closed thread is not touched ('inactive'); an unknown id gives 'not_found'.
--   Data: writes thread (last_access_dtts); reads delivery_dispatch, rider_master.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rider_thread_touch (p_thread_id text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_snap jsonb;
BEGIN
    UPDATE
        thread
    SET
        last_access_dtts = CURRENT_TIMESTAMP
    WHERE
        thread_id = p_thread_id
        AND is_active IS TRUE;
    v_snap := rider_thread_describe (p_thread_id, NULL);
    IF v_snap ->> 'result' = 'not_found' THEN
        RETURN v_snap;
    END IF;
    RETURN v_snap || jsonb_build_object('result', CASE WHEN (v_snap ->> 'is_active')::boolean THEN
            'active'
        ELSE
            'inactive'
        END);
END;
$$;

REVOKE ALL ON FUNCTION public.rider_thread_touch (text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function rider_thread_active(p_agent text, p_rider_id text, p_touch boolean) -> jsonb
--   The rider's newest open thread for this agent (also a legacy 'ORDELO-<uuid>' one), with dispatch and channel; 'none' if
--   there is no open thread. p_touch (default true) refreshes last_access_dtts like get_active_thread() did.
--   Data: reads/writes thread; reads delivery_dispatch, rider_master.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rider_thread_active (p_agent text, p_rider_id text, p_touch boolean DEFAULT TRUE)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_thread text;
BEGIN
    SELECT
        t.thread_id INTO v_thread
    FROM
        thread t
    WHERE
        t.recipient = p_rider_id
        AND (t.agent = p_agent
            OR t.agent IS NULL)
        AND t.is_active IS TRUE
    ORDER BY
        t.dtts DESC
    LIMIT 1;
    IF v_thread IS NULL THEN
        RETURN jsonb_build_object('result', 'none');
    END IF;
    IF p_touch THEN
        RETURN rider_thread_touch (v_thread);
    END IF;
    RETURN rider_thread_describe (v_thread, NULL) || jsonb_build_object('result', 'active');
END;
$$;

REVOKE ALL ON FUNCTION public.rider_thread_active (text, text, boolean) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function rider_thread_close(p_thread_id text) -> jsonb
--   Close exactly this thread: 'closed', or 'not_active' when it was already closed or does not exist.
--   Data: writes thread.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rider_thread_close (p_thread_id text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
BEGIN
    UPDATE
        thread
    SET
        is_active = FALSE
    WHERE
        thread_id = p_thread_id
        AND is_active IS TRUE;
    IF FOUND THEN
        RETURN jsonb_build_object('result', 'closed', 'thread_id', p_thread_id);
    END IF;
    RETURN jsonb_build_object('result', 'not_active', 'thread_id', p_thread_id);
END;
$$;

REVOKE ALL ON FUNCTION public.rider_thread_close (text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.rider_thread_id (p_agent text, p_dispatch_id bigint) IS 'The thread id of a dispatch: <agent>-dispatch-<dispatch_id>.';

COMMENT ON FUNCTION public.rider_thread_open (p_agent text, p_rider_id text, p_dispatch_id bigint) IS 'Open the thread of an assigned dispatch (idempotent) and close the rider''s other rider threads.';

COMMENT ON FUNCTION public.rider_thread_touch (p_thread_id text) IS 'Mark an open thread as just used and return its snapshot; refuses closed threads.';

COMMENT ON FUNCTION public.rider_thread_active (p_agent text, p_rider_id text, p_touch boolean) IS 'The rider''s open rider thread (newest), with its dispatch and channel; optionally touches it.';

COMMENT ON FUNCTION public.rider_thread_describe (p_thread_id text, p_dispatch_id bigint) IS 'Read-only snapshot of one thread, by thread id or by dispatch id.';

COMMENT ON FUNCTION public.rider_thread_close (p_thread_id text) IS 'Close exactly this thread (never every thread of the phone).';

-- =============================================================================================
-- OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================
-- Open rider threads with their dispatch and channel:
-- SELECT t.thread_id, t.recipient, t.last_access_dtts, d.dispatch_id, d.order_number, d.status, d.channel
--   FROM thread t LEFT JOIN delivery_dispatch d ON d.thread_id = t.thread_id
--  WHERE t.agent = 'ORDELO' AND t.is_active ORDER BY t.dtts DESC;
--
-- Close one stuck rider thread:
-- SELECT rider_thread_close('ORDELO-dispatch-84217');
