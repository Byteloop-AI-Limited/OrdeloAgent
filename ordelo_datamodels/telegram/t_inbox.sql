-- =============================================================================================
-- Feature SQL: Telegram durable inbox (t_inbox) - at-most-once handling of Telegram updates
-- =============================================================================================
-- See also (paths under ordelo_datamodels/): the other Telegram SQL files: telegram/t_invites.sql, telegram/t_order_alerts.sql; kitchen actions: restaurant_admin/restaurant_ready_adjust_notices.sql.
-- Run once in the Supabase SQL editor (operator step; the implementing agent never runs it).
-- Repeatable: every statement is CREATE OR REPLACE / IF NOT EXISTS, so running it again changes nothing.
-- Run it BEFORE deploying the code that calls it (channels/telegram/inbox.py). If the code is deployed
-- first the middleware fails OPEN (logs an error and handles the update without dedupe), so nothing breaks.
--
-- WHAT THIS ADDS
--   Tables     t_inbox          one row per Telegram update the bot has started to handle
--   Functions  t_inbox_claim()  insert-or-report-duplicate: the first caller for (bot_key, update_id) wins
--              t_inbox_finish() record how the handler ended ('done' | 'failed')
--
-- WHY
--   Telegram redelivers an update when the webhook is slow or answers non-2xx. Several gunicorn workers
--   can receive the retry at the same time as the original. Whether this is "the first time" is decided
--   here, in one INSERT ... ON CONFLICT, so no process keeps any state. Button taps change orders, so
--   handling one twice is not acceptable. (Decision D21 in plans/telegram-rest-admin-scaffold-plan.md.)
--
-- HOW THE PIECES FIT TOGETHER
--   Telegram -> POST /telegram/rest-admin/webhook (watomation/routers/telegram_webhook.py)
--     -> Dispatcher.feed_update -> InboxMiddleware (channels/telegram/inbox.py, outer middleware on dp.update)
--          t_inbox_claim(bot_key, update_id, kind, tuid)   -> 'new'       : run the handlers
--                                                          -> 'duplicate' : skip, log, answer 200
--          handlers run
--          t_inbox_finish(bot_key, update_id, status, err) -> row becomes 'done' or 'failed'
--
--   (Python callers: keep this list in sync with the module docstring of channels/telegram/inbox.py.
--    Overview of the whole Telegram layer: docs/telegram-layer.md)
--       InboxMiddleware / claim()   -> t_inbox_claim()
--       InboxMiddleware / finish()  -> t_inbox_finish()
--
-- ROW LIFECYCLE (t_inbox.status)
--   processing --(handler returned)--> done
--   processing --(handler raised, or the webhook time limit cancelled it)--> failed
--   A row left in 'processing' means the worker died mid-handler. It is NOT retried: the same update
--   delivered again is reported as a duplicate (at-most-once, never twice). Look at old 'processing'
--   rows when investigating a lost tap.
--
-- COLUMN NAMES
--   tuid = the sender's Telegram user id (from_user.id). NULL for updates without a user.
--   (New tables use tuid / tcid; t_invites keeps its older telegram_user_id / telegram_chat_id.)
--
-- SECURITY MODEL
--   RLS is ON with no policies and both functions are revoked from PUBLIC/anon/authenticated: only the
--   service key used by OrdeloAgent (client_ordelo_service) can call them.
--
-- NOT YET DONE
--   * Retention: the daily t_housekeeping() job (phase 4, create_t_order_alerts.sql) deletes rows older
--     than ordelo_config.TGRAM_INBOX_RETENTION_DAYS (default 7). Until it exists the table just grows slowly.
-- =============================================================================================
-- Telegram ids are not for the public API: RLS on, no policies -> only the service key can touch the table.
CREATE TABLE IF NOT EXISTS public.t_inbox (
    bot_key text NOT NULL, -- which bot received it ('rest_admin')
    update_id bigint NOT NULL, -- Telegram's update_id (unique per bot)
    kind text NOT NULL, -- Update.event_type: 'message' | 'callback_query' | ...
    tuid bigint, -- sender (from_user.id); NULL when the update has no user
    status text NOT NULL DEFAULT 'processing'::text,
    error text, -- repr of the exception when status = 'failed' (max 2000 chars)
    received_at timestamp with time zone NOT NULL DEFAULT now(),
    finished_at timestamp with time zone,
    CONSTRAINT t_inbox_pkey PRIMARY KEY (bot_key, update_id),
    CONSTRAINT t_inbox_status_check CHECK ((status = ANY (ARRAY['processing'::text, 'done'::text, 'failed'::text])))
);

-- Housekeeping scans by age.
CREATE INDEX IF NOT EXISTS t_inbox_received_at ON public.t_inbox USING btree (received_at);

ALTER TABLE public.t_inbox ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------------------------
-- t_inbox_claim(bot_key, update_id, kind, tuid): first caller wins.
-- Returns jsonb {result}:
--   new        this call inserted the row; the caller must handle the update
--   duplicate  the row already existed (+ status = its current status); the caller must skip the update
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_inbox_claim(p_bot_key text, p_update_id bigint, p_kind text, p_tuid bigint)
RETURNS jsonb LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    INSERT INTO public.t_inbox (bot_key, update_id, kind, tuid)
    VALUES (p_bot_key, p_update_id, p_kind, p_tuid)
    ON CONFLICT (bot_key, update_id) DO NOTHING;
    IF FOUND THEN
        RETURN jsonb_build_object('result', 'new');
    END IF;
    RETURN jsonb_build_object(
        'result', 'duplicate',
        'status', (SELECT i.status FROM public.t_inbox i WHERE i.bot_key = p_bot_key AND i.update_id = p_update_id));
END $$;

-- Server-only objects: nobody but the service key may call them.
REVOKE ALL ON FUNCTION public.t_inbox_claim(text, bigint, text, bigint) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- t_inbox_finish(bot_key, update_id, status, error): close a 'processing' row.
-- Returns jsonb {result}: ok | not_processing (already finished, or never claimed).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_inbox_finish(p_bot_key text, p_update_id bigint, p_status text, p_error text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF p_status NOT IN ('done', 'failed') THEN
        RAISE EXCEPTION 't_inbox_finish: bad status %', p_status;
    END IF;
    UPDATE public.t_inbox
       SET status = p_status, error = left(p_error, 2000), finished_at = now()
     WHERE bot_key = p_bot_key AND update_id = p_update_id AND status = 'processing';
    RETURN jsonb_build_object('result', CASE WHEN FOUND THEN 'ok' ELSE 'not_processing' END);
END $$;

REVOKE ALL ON FUNCTION public.t_inbox_finish(text, bigint, text, text) FROM PUBLIC, anon, authenticated;
