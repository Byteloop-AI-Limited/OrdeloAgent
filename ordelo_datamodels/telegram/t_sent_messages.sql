-- =============================================================================================
-- ordelo_datamodels/telegram/t_sent_messages.sql
-- Ledger of every Telegram message copy the bots sent (order cards, kitchen receipts, notices) so they can be edited or deleted.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  t_sent_messages
--                   One row per Telegram message copy: bot, chat, message id, owner, subject, kind, card status and state.
--               fn     t_order_card_sent(p_bot_key text, p_tcid bigint, p_message_id bigint, p_tuid bigint, p_order_number text, p_order_type text, p_rest_ref text, p_card_status text) -> jsonb
--                   Record a sent card copy, take OLDER copies in that chat for deletion, and re-check the order's status.
--               fn     t_order_card_mark(p_id bigint, p_outcome text, p_card_status text, p_close boolean) -> void
--                   Record the outcome of an edit or delete on a ledger row (generic: cards and receipts).
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   Cards (telegram/t_order_alerts.sql), receipts and notices (restaurant_admin/restaurant_ready_adjust_notices.sql) write one
--                 row per sent copy: which chat (tcid), message_id, whose copy (tuid), what it shows (subject, card_status) and its state.
--                 The ledger is not the truth (the order tables are); it only says what exists in Telegram, for cleanup and refresh.
--                 t_order_card_mark() is generic on t_sent_messages.id, so receipts reuse it.
--                 Column names: tuid = Telegram user id of the admin the copy belongs to (NULL = shared group chat, D27); tcid = chat id.
--                 Overview of the whole Telegram layer: docs/telegram-layer.md (and its HTML companion).
-- LIFECYCLE     kind: card | receipt | notice. state: live -> taken (claimed for a refresh) -> live (edited) | closed (deleted / final);
--               notices are closed at once (close_reason 'sent'). Closed rows are purged by t_housekeeping() after TGRAM_LEDGER_RETENTION_DAYS.
-- CALLED BY     t_sent_messages:
--                 sql       t_housekeeping(), t_notice_sent(), t_notice_targets(), t_order_card_mark()
--                           t_order_card_sent(), t_order_cards_stale(), t_order_cards_take(), t_receipt_sent()
--                           t_receipt_snapshot(), t_receipts_stale(), t_receipts_take()
--                 python    channels/telegram/rest_admin/order_cards/__init__.py (module-level SQL)
--               t_order_card_sent:
--                 python    channels/telegram/rest_admin/order_cards/store.py: CardStore.card_sent()
--               t_order_card_mark:
--                 python    channels/telegram/rest_admin/order_cards/store.py: CardStore.mark()
--                 python    channels/telegram/rest_admin/receipts/store.py: ReceiptStore.mark()
-- PYTHON MODEL  none
-- SECURITY      RLS ON with no policies; the functions are revoked from PUBLIC/anon/authenticated: only the service key can call them.
-- TESTS         tests/sql/test_order_cards_sql.py (loads this file into a throwaway Postgres)
--               tests/channels/telegram/test_order_card_store.py
--               tests/sql/test_order_cards_sql.py
--               tests/sql/test_order_test_script_sql.py
--               tests/sql/test_restaurant_notices_script_sql.py
--               tests/sql/test_restaurant_ready_adjust_notices_sql.py
-- GOTCHAS       dispatch_id (receipts only: which rider's receipt this copy is) was added by restaurant_admin/restaurant_ready_adjust_notices.sql.
-- SEE ALSO      telegram/t_order_alerts.sql
--               restaurant_admin/restaurant_ready_adjust_notices.sql
--               telegram/t_housekeeping.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table t_sent_messages
--   One row per Telegram message copy: bot, chat, message id, owner, subject, kind, card status and state.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.t_sent_messages (
    id bigserial NOT NULL,
    bot_key text NOT NULL,
    tcid bigint NOT NULL, -- chat holding the message (send/edit/delete target)
    message_id bigint NOT NULL,
    tuid bigint, -- admin the copy was sent to; NULL = shared (group) chat (D27)
    subject_type text NOT NULL, -- 'order' (other bots may add others)
    subject_ref text NOT NULL, -- order_number
    order_type text, -- 'delivery' | 'takeaway' when subject_type = 'order'
    kind text NOT NULL, -- 'order_card' | 'receipt' | 'notice' (the last two: restaurant_ready_adjust_notices.sql)
    rest_ref text,
    card_status text, -- status key the copy currently shows
    state text NOT NULL DEFAULT 'live' ::text,
    taken_for text,
    taken_at timestamp with time zone,
    close_reason text, -- 'deleted' | 'edited' | 'gone'
    sent_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    closed_at timestamp with time zone,
    dispatch_id integer, -- receipts only: which rider's receipt this copy is
    -- used by restaurant_admin/restaurant_ready_adjust_notices.sql
    CONSTRAINT t_sent_messages_pkey PRIMARY KEY (id),
    CONSTRAINT t_sent_messages_bot_key_tcid_message_id_key UNIQUE (bot_key, tcid, message_id),
    CONSTRAINT t_sent_messages_state_check CHECK ((state = ANY (ARRAY['live'::text, 'taken'::text, 'closed'::text]))),
    CONSTRAINT t_sent_messages_taken_for_check CHECK ((taken_for = ANY (ARRAY['delete'::text, 'edit'::text])))
);

CREATE INDEX IF NOT EXISTS t_sent_messages_closed ON public.t_sent_messages USING btree (closed_at)
WHERE (state = 'closed'::text);

CREATE INDEX IF NOT EXISTS t_sent_messages_receipts ON public.t_sent_messages USING btree (subject_ref, tcid)
WHERE ((kind = 'receipt'::text) AND (state <> 'closed'::text));

CREATE INDEX IF NOT EXISTS t_sent_messages_subject ON public.t_sent_messages USING btree (subject_type, subject_ref)
WHERE (state <> 'closed'::text);

ALTER TABLE public.t_sent_messages ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------------------------
-- function t_order_card_sent(p_bot_key text, p_tcid bigint, p_message_id bigint, p_tuid bigint, p_order_number text, p_order_type text, p_rest_ref text, p_card_status text) -> jsonb
--   Record a sent card copy, take OLDER copies in that chat for deletion, and re-check the order's status.
--   Data: writes t_sent_messages; calls t_order_card_row(), t_order_card_status().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 6. t_order_card_sent(...): record a copy that was just sent and take this chat's OLDER copies of the order.
--    One transaction. Returns jsonb {previous:[{id, tcid, message_id}], order_status} where order_status is the
--    order's status RIGHT NOW ('gone' if the order vanished): the "DB check after sending" (D24).
--    Idempotent on (bot_key, tcid, message_id).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_card_sent (p_bot_key text, p_tcid bigint, p_message_id bigint, p_tuid bigint, p_order_number text, p_order_type text, p_rest_ref text, p_card_status text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_id bigint;
    v_prev jsonb;
    o record;
BEGIN
    INSERT INTO public.t_sent_messages (bot_key, tcid, message_id, tuid, subject_type, subject_ref, order_type, kind, rest_ref, card_status)
        VALUES (p_bot_key, p_tcid, p_message_id, p_tuid, 'order', p_order_number, p_order_type, 'order_card', p_rest_ref, p_card_status)
    ON CONFLICT (bot_key, tcid, message_id)
        DO NOTHING
    RETURNING
        id INTO v_id;
    IF v_id IS NULL THEN
        SELECT
            m.id INTO v_id
        FROM
            public.t_sent_messages m
        WHERE
            m.bot_key = p_bot_key
            AND m.tcid = p_tcid
            AND m.message_id = p_message_id;
    END IF;

    WITH older AS (
        SELECT
            m.id
        FROM
            public.t_sent_messages m
        WHERE
            m.bot_key = p_bot_key
            AND m.tcid = p_tcid
            AND m.subject_type = 'order'
            AND m.subject_ref = p_order_number
            AND m.order_type IS NOT DISTINCT FROM p_order_type
            AND m.kind = 'order_card'
            AND m.state = 'live'
            AND m.id < v_id
        FOR UPDATE
            SKIP LOCKED
),
taken AS (
    UPDATE
        public.t_sent_messages m
    SET
        state = 'taken',
        taken_for = 'delete',
        taken_at = now(),
        updated_at = now()
    FROM
        older
    WHERE
        m.id = older.id
    RETURNING
        m.id,
        m.tcid,
        m.message_id
)
SELECT
    COALESCE(jsonb_agg(jsonb_build_object('id', t.id, 'tcid', t.tcid, 'message_id', t.message_id)), '[]'::jsonb) INTO v_prev
FROM
    taken t;

    SELECT
        * INTO o
    FROM
        public.t_order_card_row (p_order_number, p_order_type);
    RETURN jsonb_build_object('previous', v_prev, 'order_status', COALESCE(public.t_order_card_status (o.rcs, o.pickup_time), 'gone'));
END
$$;

REVOKE ALL ON FUNCTION public.t_order_card_sent (text, bigint, bigint, bigint, text, text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_order_card_mark(p_id bigint, p_outcome text, p_card_status text, p_close boolean) -> void
--   Record the outcome of an edit or delete on a ledger row (generic: cards and receipts).
--   Data: writes t_sent_messages.
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 9. t_order_card_mark(id, outcome, card_status, close): record what happened to a claimed copy.
--    outcome: 'edited' | 'deleted' | 'gone'. 'deleted' and 'gone' always close the row. 'edited' without
--    close returns the copy to 'live' showing p_card_status. Only a 'taken' row changes (idempotent).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_card_mark (p_id bigint, p_outcome text, p_card_status text, p_close boolean)
    RETURNS void
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
BEGIN
    IF p_outcome NOT IN ('edited', 'deleted', 'gone') THEN
        RAISE EXCEPTION 't_order_card_mark: bad outcome %', p_outcome;
    END IF;
    IF p_close OR p_outcome IN ('deleted', 'gone') THEN
        UPDATE
            public.t_sent_messages
        SET
            state = 'closed',
            close_reason = p_outcome,
            closed_at = now(),
            updated_at = now(),
            taken_for = NULL,
            card_status = COALESCE(p_card_status, card_status)
        WHERE
            id = p_id
            AND state = 'taken';
    ELSE
        UPDATE
            public.t_sent_messages
        SET
            state = 'live',
            card_status = p_card_status,
            taken_for = NULL,
            taken_at = NULL,
            updated_at = now()
        WHERE
            id = p_id
            AND state = 'taken';
    END IF;
END
$$;

REVOKE ALL ON FUNCTION public.t_order_card_mark (bigint, text, text, boolean) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.t_sent_messages IS 'One row per Telegram message copy: bot, chat, message id, owner, subject, kind, card status and state.';

COMMENT ON FUNCTION public.t_order_card_sent (p_bot_key text, p_tcid bigint, p_message_id bigint, p_tuid bigint, p_order_number text, p_order_type text, p_rest_ref text, p_card_status text) IS 'Record a sent card copy, take OLDER copies in that chat for deletion, and re-check the order''s status.';

COMMENT ON FUNCTION public.t_order_card_mark (p_id bigint, p_outcome text, p_card_status text, p_close boolean) IS 'Record the outcome of an edit or delete on a ledger row (generic: cards and receipts).';
