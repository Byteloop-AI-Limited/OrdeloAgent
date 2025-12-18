drop table thread;

create table thread (
    thread_id text,
    agent text,
    recipient varchar(12),
    is_active boolean,
    retain_thread boolean default false,
    dt date default current_date,
    dtts timestamp default current_timestamp,
    last_access_dtts timestamp default current_timestamp,
    CONSTRAINT thread_pkey PRIMARY KEY (thread_id)
);
CREATE INDEX idx_thread_agent_thread_id ON thread (agent, thread_id);

-- Function to get active thread and update last_access_dtts
CREATE OR REPLACE FUNCTION get_active_thread(p_agent text, p_recipient varchar)
RETURNS TABLE (
    thread_id text,
    agent text,
    recipient varchar,
    is_active boolean,
    retain_thread boolean,
    dt date,
    dtts timestamp,
    last_access_dtts timestamp
) AS $$
BEGIN
    -- Update last_access_dtts for matching active threads and return them
    RETURN QUERY
    WITH updated AS (
        UPDATE thread
        SET last_access_dtts = CURRENT_TIMESTAMP,
            agent = COALESCE(thread.agent, p_agent)
        WHERE thread.recipient = p_recipient 
          AND thread.is_active = TRUE
          AND (thread.agent = p_agent OR thread.agent IS NULL)
        RETURNING 
            thread.thread_id,
            thread.agent,
            thread.recipient,
            thread.is_active,
            thread.retain_thread,
            thread.dt,
            thread.dtts,
            thread.last_access_dtts
    )
    SELECT * FROM updated
    ORDER BY updated.dtts DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Function to spawn a new thread
CREATE OR REPLACE FUNCTION create_thread(p_agent text, p_recipient varchar)
RETURNS TABLE (
    thread_id text,
    agent text,
    recipient varchar,
    is_active boolean,
    retain_thread boolean,
    dt date,
    dtts timestamp,
    last_access_dtts timestamp
) AS $$
DECLARE
    v_thread_id text;
BEGIN
    -- Generate UUID for thread_id, prepended with agent name
    v_thread_id := p_agent || '-' || gen_random_uuid()::text;
    
    -- Insert new thread and return it
    RETURN QUERY
    INSERT INTO thread (thread_id, agent, recipient, is_active, last_access_dtts)
    VALUES (v_thread_id, p_agent, p_recipient, TRUE, CURRENT_TIMESTAMP)
    RETURNING 
        thread.thread_id,
        thread.agent,
        thread.recipient,
        thread.is_active,
        thread.retain_thread,
        thread.dt,
        thread.dtts,
        thread.last_access_dtts;
END;
$$ LANGUAGE plpgsql;

-- Function to make threads inactive
CREATE OR REPLACE FUNCTION make_threads_inactive(p_agent text, p_recipient varchar)
RETURNS integer AS $$
DECLARE
    v_affected_rows integer;
BEGIN
    UPDATE thread
    SET is_active = FALSE
    WHERE recipient = p_recipient
      AND (thread.agent = p_agent OR thread.agent IS NULL)
      AND retain_thread IS NOT TRUE;
    
    GET DIAGNOSTICS v_affected_rows = ROW_COUNT;
    RETURN v_affected_rows;
END;
$$ LANGUAGE plpgsql;

-- Function to get stale active threads that are candidates for inactivation
CREATE OR REPLACE FUNCTION get_stale_active_threads(p_agent text, p_stale_minutes integer DEFAULT 5)
RETURNS TABLE (
    thread_id text,
    agent text,
    recipient varchar,
    is_active boolean,
    retain_thread boolean,
    dt date,
    dtts timestamp,
    last_access_dtts timestamp
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.thread_id,
        t.agent,
        t.recipient,
        t.is_active,
        t.retain_thread,
        t.dt,
        t.dtts,
        t.last_access_dtts
    FROM thread t
    WHERE t.is_active = TRUE
      AND t.retain_thread IS NOT TRUE
      AND (t.agent = p_agent OR t.agent IS NULL)
      AND t.last_access_dtts IS NOT NULL
      AND t.last_access_dtts < (CURRENT_TIMESTAMP - make_interval(mins => p_stale_minutes))
    ORDER BY t.last_access_dtts ASC;
END;
$$ LANGUAGE plpgsql;

-- Function to get or spawn thread (main function)
CREATE OR REPLACE FUNCTION get_or_create_thread(p_agent text, p_recipient varchar)
RETURNS TABLE (
    thread_id text,
    agent text,
    recipient varchar,
    is_active boolean,
    retain_thread boolean,
    dt date,
    dtts timestamp,
    last_access_dtts timestamp,
    was_created boolean
) AS $$
DECLARE
    v_active_thread RECORD;
BEGIN
    -- Try to get an active thread
    SELECT * INTO v_active_thread
    FROM get_active_thread(p_agent, p_recipient)
    LIMIT 1;
    
    IF v_active_thread.thread_id IS NOT NULL THEN
        -- Active thread exists, return it with was_created = false
        RETURN QUERY
        SELECT 
            v_active_thread.thread_id,
            v_active_thread.agent,
            v_active_thread.recipient,
            v_active_thread.is_active,
            v_active_thread.retain_thread,
            v_active_thread.dt,
            v_active_thread.dtts,
            v_active_thread.last_access_dtts,
            FALSE as was_created;
    ELSE
        -- No active thread, spawn a new one and return with was_created = true
        RETURN QUERY
        SELECT 
            ct.thread_id,
            ct.agent,
            ct.recipient,
            ct.is_active,
            ct.retain_thread,
            ct.dt,
            ct.dtts,
            ct.last_access_dtts,
            TRUE as was_created
        FROM create_thread(p_agent, p_recipient) ct;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to retain thread for active thread
CREATE OR REPLACE FUNCTION retain_thread(p_agent text, p_recipient varchar)
RETURNS TABLE (
    thread_id text,
    agent text,
    recipient varchar,
    is_active boolean,
    retain_thread boolean,
    dt date,
    dtts timestamp,
    last_access_dtts timestamp
) AS $$
DECLARE
    v_active_thread RECORD;
BEGIN
    -- Get the active thread for the recipient
    SELECT * INTO v_active_thread
    FROM get_active_thread(p_agent, p_recipient)
    LIMIT 1;
    
    -- If active thread exists, update retain_thread to true
    IF v_active_thread.thread_id IS NOT NULL THEN
        RETURN QUERY
        UPDATE thread
        SET retain_thread = TRUE
        WHERE thread.thread_id = v_active_thread.thread_id
          AND (thread.agent = p_agent OR thread.agent IS NULL)
        RETURNING 
            thread.thread_id,
            thread.agent,
            thread.recipient,
            thread.is_active,
            thread.retain_thread,
            thread.dt,
            thread.dtts,
            thread.last_access_dtts;
    END IF;
END;
$$ LANGUAGE plpgsql;
