-- =============================================================================================
-- ordelo_datamodels/telegram/t_inbox.sql
-- Telegram durable inbox: at-most-once handling of selected consequential updates across workers.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  t_inbox
--                   One row per selected Telegram update a protected handler claimed, keyed by (bot_key, update_id).
--               fn     t_inbox_claim(p_bot_key text, p_update_id bigint, p_kind text, p_tuid bigint) -> jsonb
--                   Insert the update or report it as a duplicate: returns {result: 'new'} for the first caller, {result: 'duplicate', status} after.
--               fn     t_inbox_finish(p_bot_key text, p_update_id bigint, p_status text, p_error text) -> jsonb
--                   Record how the handler ended: status 'done' or 'failed' with an optional error.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none when applied.
-- HOW IT FITS   Selected consequential handlers claim by (bot_key, update_id) before their work. Read-only, fallback and unmatched
--                 updates make no inbox call. A retry can reach another worker; one INSERT ... ON CONFLICT decides the first caller.
--                   Telegram -> POST /telegram/rest-admin/webhook (watomation/routers/telegram_webhook.py)
--                     -> Dispatcher.feed_update -> selected handler -> process_once() (channels/telegram/inbox.py)
--                          t_inbox_claim(bot_key, update_id, kind, tuid)   -> 'new': run the handlers | 'duplicate': skip, answer 200
--                          handlers run
--                          t_inbox_finish(bot_key, update_id, status, err) -> 'done' | 'failed'
--                 If the claim RPC is unavailable process_once() fails OPEN (logs and handles without dedupe).
--                 For rider agent turns, 'done' means the turn was queued, not that it finished.
--                 Overview of the whole Telegram layer: docs/telegram-layer.md (and its HTML companion).
-- LIFECYCLE     t_inbox.status: processing -> done | failed. A row left in 'processing' means the worker died mid-handler; it is NOT
--               retried (the same update again is a duplicate: at-most-once). Look at old 'processing' rows when a tap was lost.
--               Column names: tuid = sender's Telegram user id.
-- CALLED BY     t_inbox:
--                 sql       t_housekeeping(), t_inbox_claim(), t_inbox_finish()
--                 python    channels/telegram/inbox.py (module-level SQL)
--               t_inbox_claim:
--                 python    channels/telegram/inbox.py: claim()
--               t_inbox_finish:
--                 python    channels/telegram/inbox.py: finish()
-- PYTHON MODEL  none
-- SECURITY      t_inbox: RLS ON; Supabase default grants (anon and authenticated can read and write)
--               t_inbox_claim(): service role only
--               t_inbox_finish(): service role only
-- TESTS         tests/sql/test_t_inbox_sql.py (loads this file into a throwaway Postgres)
--               tests/channels/telegram/conftest.py
--               tests/channels/telegram/test_inbox.py
--               tests/sql/test_order_cards_sql.py
--               tests/sql/test_t_inbox_sql.py
-- GOTCHAS       Retention: t_housekeeping() deletes rows older than TGRAM_INBOX_RETENTION_DAYS (7), but it is NOT scheduled on live (docs/to-do.md).
-- SEE ALSO      telegram/t_housekeeping.sql
--               telegram/t_invites.sql
--               docs/telegram-layer.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table t_inbox
--   One row per Telegram update a bot started handling, keyed by (bot_key, update_id).
-- ---------------------------------------------------------------------------------------------
-- Telegram ids are not for the public API: RLS on, no policies -> only the service key can touch the table.
CREATE TABLE IF NOT EXISTS public.t_inbox (
    bot_key text NOT NULL, -- which bot received it ('rest_admin')
    update_id bigint NOT NULL, -- Telegram's update_id (unique per bot)
    kind text NOT NULL, -- Update.event_type: 'message' | 'callback_query' | ...
    tuid bigint, -- sender (from_user.id); NULL when the update has no user
    status text NOT NULL DEFAULT 'processing' ::text,
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
-- function t_inbox_claim(p_bot_key text, p_update_id bigint, p_kind text, p_tuid bigint) -> jsonb
--   Insert the update or report it as a duplicate: returns {result: 'new'} for the first caller, {result: 'duplicate', status} after.
--   Data: writes t_inbox.
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- t_inbox_claim(bot_key, update_id, kind, tuid): first caller wins.
-- Returns jsonb {result}:
--   new        this call inserted the row; the caller must handle the update
--   duplicate  the row already existed (+ status = its current status); the caller must skip the update
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_inbox_claim (p_bot_key text, p_update_id bigint, p_kind text, p_tuid bigint)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
BEGIN
    INSERT INTO public.t_inbox (bot_key, update_id, kind, tuid)
        VALUES (p_bot_key, p_update_id, p_kind, p_tuid)
    ON CONFLICT (bot_key, update_id)
        DO NOTHING;
    IF FOUND THEN
        RETURN jsonb_build_object('result', 'new');
    END IF;
    RETURN jsonb_build_object('result', 'duplicate', 'status', (
            SELECT
                i.status
            FROM public.t_inbox i
            WHERE
                i.bot_key = p_bot_key
                AND i.update_id = p_update_id));
END
$$;

-- Server-only objects: nobody but the service key may call them.
REVOKE ALL ON FUNCTION public.t_inbox_claim (text, bigint, text, bigint) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_inbox_finish(p_bot_key text, p_update_id bigint, p_status text, p_error text) -> jsonb
--   Record how the handler ended: status 'done' or 'failed' with an optional error.
--   Data: writes t_inbox.
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- t_inbox_finish(bot_key, update_id, status, error): close a 'processing' row.
-- Returns jsonb {result}: ok | not_processing (already finished, or never claimed).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_inbox_finish (p_bot_key text, p_update_id bigint, p_status text, p_error text DEFAULT NULL)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
BEGIN
    IF p_status NOT IN ('done', 'failed') THEN
        RAISE EXCEPTION 't_inbox_finish: bad status %', p_status;
    END IF;
    UPDATE
        public.t_inbox
    SET
        status = p_status,
        error =
    LEFT (p_error,
        2000),
    finished_at = now()
WHERE
    bot_key = p_bot_key
        AND update_id = p_update_id
        AND status = 'processing';
    RETURN jsonb_build_object('result', CASE WHEN FOUND THEN
            'ok'
        ELSE
            'not_processing'
        END);
END
$$;

REVOKE ALL ON FUNCTION public.t_inbox_finish (text, bigint, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.t_inbox IS 'One row per Telegram update a bot started handling, keyed by (bot_key, update_id).';

COMMENT ON FUNCTION public.t_inbox_claim (p_bot_key text, p_update_id bigint, p_kind text, p_tuid bigint) IS 'Insert the update or report it as a duplicate: returns {result: ''new''} for the first caller, {result: ''duplicate'', status} after.';

COMMENT ON FUNCTION public.t_inbox_finish (p_bot_key text, p_update_id bigint, p_status text, p_error text) IS 'Record how the handler ended: status ''done'' or ''failed'' with an optional error.';
