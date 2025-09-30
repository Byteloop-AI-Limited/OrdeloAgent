-- CREATE TABLE public.thread (
--   thread_id text NOT NULL,
--   recipient character varying(255) NOT NULL,
--   thread_ts timestamp without time zone NOT NULL,
--   is_active boolean NOT NULL DEFAULT true,
--   CONSTRAINT thread_pkey PRIMARY KEY (thread_id)
-- );

-- Migration: Add last_access_dtts column to existing table
-- ALTER TABLE public.thread ADD COLUMN IF NOT EXISTS last_access_dtts timestamp;
-- Migration: Rename from_number to recipient
-- ALTER TABLE public.thread RENAME COLUMN from_number TO recipient;

create table public.thread (
    thread_id text,
    recipient varchar(12),
    is_active boolean,
    retain_thread boolean default false,
    dt date default current_date,
    dtts timestamp default current_timestamp,
    last_access_dtts timestamp,
    CONSTRAINT thread_pkey PRIMARY KEY (thread_id)
);

-- Function to get active thread and update last_access_dtts
CREATE OR REPLACE FUNCTION get_active_thread(p_recipient varchar)
RETURNS TABLE (
    thread_id text,
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
        SET last_access_dtts = CURRENT_TIMESTAMP
        WHERE thread.recipient = p_recipient 
          AND thread.is_active = TRUE
        RETURNING 
            thread.thread_id,
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

-- Function to create a new thread
CREATE OR REPLACE FUNCTION create_thread(p_recipient varchar)
RETURNS TABLE (
    thread_id text,
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
    -- Generate UUID for thread_id
    v_thread_id := gen_random_uuid()::text;
    
    -- Insert new thread and return it
    RETURN QUERY
    INSERT INTO thread (thread_id, recipient, is_active)
    VALUES (v_thread_id, p_recipient, TRUE)
    RETURNING 
        thread.thread_id,
        thread.recipient,
        thread.is_active,
        thread.retain_thread,
        thread.dt,
        thread.dtts,
        thread.last_access_dtts;
END;
$$ LANGUAGE plpgsql;

-- Function to make threads inactive
CREATE OR REPLACE FUNCTION make_threads_inactive(p_recipient varchar)
RETURNS integer AS $$
DECLARE
    v_affected_rows integer;
BEGIN
    UPDATE thread
    SET is_active = FALSE
    WHERE recipient = p_recipient;
    
    GET DIAGNOSTICS v_affected_rows = ROW_COUNT;
    RETURN v_affected_rows;
END;
$$ LANGUAGE plpgsql;

-- Function to get or create thread (main function)
CREATE OR REPLACE FUNCTION get_or_create_thread(p_recipient varchar)
RETURNS TABLE (
    thread_id text,
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
    FROM get_active_thread(p_recipient)
    LIMIT 1;
    
    IF v_active_thread.thread_id IS NOT NULL THEN
        -- Active thread exists, return it with was_created = false
        RETURN QUERY
        SELECT 
            v_active_thread.thread_id,
            v_active_thread.recipient,
            v_active_thread.is_active,
            v_active_thread.retain_thread,
            v_active_thread.dt,
            v_active_thread.dtts,
            v_active_thread.last_access_dtts,
            FALSE as was_created;
    ELSE
        -- No active thread, create a new one and return with was_created = true
        RETURN QUERY
        SELECT 
            ct.thread_id,
            ct.recipient,
            ct.is_active,
            ct.retain_thread,
            ct.dt,
            ct.dtts,
            ct.last_access_dtts,
            TRUE as was_created
        FROM create_thread(p_recipient) ct;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to retain thread for active thread
CREATE OR REPLACE FUNCTION retain_thread(p_recipient varchar)
RETURNS TABLE (
    thread_id text,
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
    FROM get_active_thread(p_recipient)
    LIMIT 1;
    
    -- If active thread exists, update retain_thread to true
    IF v_active_thread.thread_id IS NOT NULL THEN
        RETURN QUERY
        UPDATE thread
        SET retain_thread = TRUE
        WHERE thread.thread_id = v_active_thread.thread_id
        RETURNING 
            thread.thread_id,
            thread.recipient,
            thread.is_active,
            thread.retain_thread,
            thread.dt,
            thread.dtts,
            thread.last_access_dtts;
    END IF;
END;
$$ LANGUAGE plpgsql;