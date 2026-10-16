-- =============================================================================================
-- Feature SQL: Telegram order cards - schedule (t_order_alerts), ledger (t_sent_messages), sweep, housekeeping
-- =============================================================================================
-- See also (paths under ordelo_datamodels/): sibling files: restaurant_admin/restaurant_order_decision.sql (accept / decline) and restaurant_admin/restaurant_ready_adjust_notices.sql (Ready / adjust, receipts and notices, which reuse t_sent_messages).
-- Run once in the Supabase SQL editor (operator step; the implementing agent never runs it).
-- Repeatable: every statement is CREATE OR REPLACE / IF NOT EXISTS / ON CONFLICT DO NOTHING.
-- Run it AFTER create_t_inbox.sql, create_t_invites.sql and restaurant_order_decision.sql (it reads
-- t_invites, t_inbox and restaurant_admin_label()) and AFTER dispatch/job_rider_pickup_alerts.sql
-- (it reuses parse_alert_offsets() and the http extension). Run it BEFORE deploying the code that calls it
-- (channels/telegram/rest_admin/order_cards/store.py, watomation/routers/telegram_order_alerts.py).
-- Nothing is sent until the operator schedules the sweep (last section of this file).
--
-- WHAT THIS ADDS
--   Tables     t_order_alerts     the schedule: one row per order x reminder offset (0/15/30/45 s by default)
--              t_sent_messages    the ledger: where each Telegram copy of an order card lives (cleanup only)
--   Functions  t_order_card_status()        order state -> card status key (IMMUTABLE)
--              t_order_card_row()           the order's current state, delivery or takeaway
--              t_order_card_destinations()  WHERE cards go (the one place that says so)
--              t_order_card_snapshot()      everything needed to draw the card, one DB read
--              t_order_card_sent()          record a sent copy, take older copies, re-check the order
--              t_order_cards_stale()        copies that no longer show the truth (read-only)
--              t_order_cards_take()         claim those copies for one refresh pass
--              t_order_card_mark()          record the outcome of an edit / delete
--              job_t_order_alerts()         the 5-second sweep: seed, cancel, find due reminders and stale cards, POST
--              t_housekeeping()             daily purge of old t_inbox / t_sent_messages / t_order_alerts rows
--   Config     TGRAM_ORDER_ALERT_OFFSETS_SECS ('0,15,30,45'), TGRAM_INBOX_RETENTION_DAYS ('7'),
--              TGRAM_LEDGER_RETENTION_DAYS ('30'); a per-restaurant <REF>_TGRAM_ORDER_ALERT_OFFSETS_SECS wins.
--
-- WHY (plans/telegram-rest-admin-scaffold-plan.md, decisions D12, D14, D22, D24, D26)
--   Linked restaurant admins get the order card in Telegram at the configured offsets after the order arrives;
--   each new copy replaces the previous one in that chat (so the phone notifies again); every copy follows
--   the order until it is final (accepted on WhatsApp, timed out, declined, manual SQL). The database is
--   authoritative and is checked before every send; the ledger only remembers what to tidy up.
--
-- HOW THE PIECES FIT TOGETHER
--   pg_cron every 5 s -> job_t_order_alerts()
--        SEED     delivery_summary + takeaway_summary rows still 'restaurant_unconfirmed' (< 15 min old) with at least
--                 one destination -> one t_order_alerts checkpoint per offset
--        CANCEL   pending checkpoints of orders that are no longer unconfirmed
--        DUE      pending checkpoints with due_at <= now(); one winner per order (the largest offset)
--        STALE    up to 50 orders with copies that show an old status or a revoked viewer
--        POST     ORDELO_APP_URL/telegram/rest-admin/order-alerts {reminders:[...], refreshes:[...]}
--        MARK     only on a 2xx answer: superseded first, then winners 'sent'
--   -> watomation/routers/telegram_order_alerts.py (background tasks)
--        OrderCards.remind(order, n, of)  -> snapshot -> send per destination -> t_order_card_sent -> delete old copies
--        OrderCards.refresh(order)        -> snapshot -> t_order_cards_take -> edit/delete -> t_order_card_mark
--
--   Python callers (keep in sync with the module docstring of channels/telegram/rest_admin/order_cards/store.py):
--       CardStore.snapshot()          -> t_order_card_snapshot()   (destinations come from t_order_card_destinations())
--       CardStore.card_sent()         -> t_order_card_sent()
--       CardStore.take_for_refresh()  -> t_order_cards_take()
--       CardStore.mark()              -> t_order_card_mark()
--       (job_t_order_alerts, t_housekeeping, t_order_cards_stale and t_order_card_status are called only by
--        pg_cron and by the other functions here)
--       phase 5 appends t_order_decide() / t_order_set_pickup() to restaurant_order_decision.sql.
--   Card status keys MUST match channels/telegram/rest_admin/order_cards/model.py (Status):
--       awaiting | accepted | pickup_set | declined | auto_accepted | gone
--
-- COLUMN NAMES  tuid = Telegram user id of the admin the copy belongs to (NULL = shared group chat, D27);
--               tcid = Telegram chat id holding the message (send / edit / delete target).
--
-- CONCURRENCY   Up to 3 gunicorn workers may run remind / refresh for the same order at once. Nothing is kept
--               in process: copies are claimed in SQL (state 'taken', FOR UPDATE SKIP LOCKED); a claim not
--               finished within 30 seconds is offered again by the sweep. A newer copy only deletes OLDER ones
--               (id <), so two reminders in flight can never delete each other.
--
-- SECURITY MODEL  RLS ON with no policies; all functions revoked from PUBLIC/anon/authenticated: only the
--               service key (client_ordelo_service) can call them.
--
-- NOT YET DONE
--   * The card destination is looked up by the SUMMARY's rest_ref (the order-number prefix). A restaurant whose
--     orders use an alias prefix (config/params.py _REST_REF_ALIAS_MAP) has no restaurant_master row of that name
--     and gets no cards until the alias is resolved here.
--   * Group chats (D27) are added by extending t_order_card_destinations() with a UNION ALL branch.
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Tables
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.t_order_alerts (
    id           bigserial PRIMARY KEY,
    bot_key      text        NOT NULL DEFAULT 'rest_admin',
    order_number text        NOT NULL,
    order_type   text        NOT NULL CHECK (order_type IN ('delivery', 'takeaway')),
    rest_ref     text        NOT NULL,
    offset_secs  int         NOT NULL,
    n            int         NOT NULL,                       -- 1-based position in the offset list ("reminder n of of_n")
    of_n         int         NOT NULL,
    due_at       timestamptz NOT NULL,                       -- summary.dtts + offset
    status       text        NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'sent', 'superseded', 'cancelled')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    swept_at     timestamptz,
    UNIQUE (bot_key, order_number, offset_secs)
);
CREATE INDEX IF NOT EXISTS t_order_alerts_due ON public.t_order_alerts (due_at) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS public.t_sent_messages (
    id            bigserial PRIMARY KEY,
    bot_key       text        NOT NULL,
    tcid          bigint      NOT NULL,                      -- chat holding the message (send/edit/delete target)
    message_id    bigint      NOT NULL,
    tuid          bigint,                                    -- admin the copy was sent to; NULL = shared (group) chat (D27)
    subject_type  text        NOT NULL,                      -- 'order' (other bots may add others)
    subject_ref   text        NOT NULL,                      -- order_number
    order_type    text,                                      -- 'delivery' | 'takeaway' when subject_type = 'order'
    kind          text        NOT NULL,                      -- 'order_card' | 'receipt' | 'notice' (the last two: restaurant_ready_adjust_notices.sql)
    rest_ref      text,
    card_status   text,                                      -- status key the copy currently shows
    state         text        NOT NULL DEFAULT 'live' CHECK (state IN ('live', 'taken', 'closed')),
    taken_for     text        CHECK (taken_for IN ('delete', 'edit')),
    taken_at      timestamptz,
    close_reason  text,                                      -- 'deleted' | 'edited' | 'gone'
    sent_at       timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    closed_at     timestamptz,
    UNIQUE (bot_key, tcid, message_id)
);
CREATE INDEX IF NOT EXISTS t_sent_messages_subject ON public.t_sent_messages (subject_type, subject_ref) WHERE state <> 'closed';
CREATE INDEX IF NOT EXISTS t_sent_messages_closed  ON public.t_sent_messages (closed_at) WHERE state = 'closed';

ALTER TABLE public.t_order_alerts  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.t_sent_messages ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------------------------
-- 2. t_order_card_status(restaurant_confirmation_status, pickup_time): the card status key.
--    NULL in -> NULL out (no such order). 'restaurant_timedout' without a pickup is still 'awaiting': the
--    timeout handler sets the pickup within seconds. Same keys as model.py Status.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_card_status(p_rcs text, p_pickup timestamptz)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN p_rcs IS NULL                                              THEN NULL
        WHEN p_rcs = 'restaurant_unconfirmed'                           THEN 'awaiting'
        WHEN p_rcs IN ('restaurant_decline', 'auto_decline')            THEN 'declined'
        WHEN p_rcs IN ('restaurant_accept', 'restaurant_pickuptime_adjusted')
                                                                        THEN CASE WHEN p_pickup IS NULL THEN 'accepted' ELSE 'pickup_set' END
        WHEN p_rcs IN ('auto_accept', 'restaurant_timedout')            THEN CASE WHEN p_pickup IS NULL THEN 'awaiting' ELSE 'auto_accepted' END
        ELSE 'awaiting'
    END
$$;

-- ---------------------------------------------------------------------------------------------
-- 3. t_order_card_row(order_number, order_type): the order's current state (0 or 1 row).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_card_row(p_order_number text, p_order_type text)
RETURNS TABLE (order_number text, order_type text, rest_ref text, rest_name text, dtts timestamptz,
               rcs text, pickup_time timestamptz, admin_phone text)
LANGUAGE sql STABLE SET search_path = public AS $$
    SELECT s.order_number::text, 'delivery'::text, s.rest_ref::text, s.rest_name::text, s.dtts,
           s.restaurant_confirmation_status::text, s.pickup_time, s.restaurant_admin::text
      FROM public.delivery_summary s
     WHERE p_order_type = 'delivery' AND s.order_number = p_order_number
    UNION ALL
    SELECT s.order_number::text, 'takeaway'::text, s.rest_ref::text, s.rest_name::text, s.dtts,
           s.restaurant_confirmation_status::text, s.pickup_time, s.restaurant_admin::text
      FROM public.takeaway_summary s
     WHERE p_order_type = 'takeaway' AND s.order_number = p_order_number
$$;

-- ---------------------------------------------------------------------------------------------
-- 4. t_order_card_destinations(bot_key, rest_ref): WHERE cards for this restaurant go. The ONE place that says so.
--    Today: one private chat per admin who (D14) has a claimed invite for the restaurant AND whose invite phone
--    is in restaurant_master.admins (digits compared). DISTINCT ON the chat so a person holding two invites
--    gets one card. Later (D27): UNION ALL linked group chats with tuid / phone NULL.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_card_destinations(p_bot_key text, p_rest_ref text)
RETURNS TABLE (tcid bigint, tuid bigint, phone text, label text)
LANGUAGE sql STABLE SET search_path = public AS $$
    SELECT DISTINCT ON (i.telegram_chat_id)
           i.telegram_chat_id, i.telegram_user_id, i.phone_number, i.telegram_first_name
      FROM public.t_invites i
      JOIN public.restaurant_master rm ON rm.rest_ref = i.rest_ref
     WHERE i.bot_key = p_bot_key
       AND i.rest_ref = p_rest_ref
       AND i.status = 'claimed'
       AND i.telegram_chat_id IS NOT NULL
       AND i.phone_number IN (SELECT regexp_replace(a, '\D', '', 'g') FROM unnest(rm.admins) AS a)
     ORDER BY i.telegram_chat_id, i.claimed_at DESC NULLS LAST
$$;

-- ---------------------------------------------------------------------------------------------
-- 5. t_order_card_snapshot(bot_key, order_number, order_type): everything needed to draw the card.
--    NULL when the order does not exist. Returns jsonb
--      {status, rest_ref, facts:{order_number, order_type, rest_name, total, items[], ordered_at},
--       decided_by:{label, phone}|null, pickup_at, destinations:[{tcid, tuid, phone, label}]}
--    This is the "DB check before sending" (D24).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_card_snapshot(p_bot_key text, p_order_number text, p_order_type text)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path = public AS $$
DECLARE
    r public.food_order%ROWTYPE;
    o record;
    v_items jsonb;
    v_total text;
    v_phone text;
BEGIN
    SELECT * INTO o FROM public.t_order_card_row(p_order_number, p_order_type);
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    SELECT * INTO r FROM public.food_order f WHERE f.order_number = p_order_number;
    SELECT COALESCE(jsonb_agg(oi.quantity::text || 'x ' || oi.product_name ORDER BY oi.product_name), '[]'::jsonb)
      INTO v_items
      FROM public.order_item oi WHERE oi.order_id = r.order_id;
    v_total := CASE WHEN r.total_price IS NULL THEN ''
                    ELSE '£' || to_char(r.total_price, 'FM999999990.00') END;
    v_phone := NULLIF(regexp_replace(COALESCE(o.admin_phone, ''), '\D', '', 'g'), '');
    RETURN jsonb_build_object(
        'status',   public.t_order_card_status(o.rcs, o.pickup_time),
        'rest_ref', o.rest_ref,
        'facts',    jsonb_build_object(
                        'order_number', o.order_number,
                        'order_type',   o.order_type,
                        'rest_name',    o.rest_name,
                        'total',        v_total,
                        'items',        v_items,
                        'ordered_at',   o.dtts),
        'decided_by', CASE WHEN v_phone IS NULL THEN NULL
                           ELSE jsonb_build_object('label', public.restaurant_admin_label(v_phone), 'phone', v_phone) END,
        'pickup_at', o.pickup_time,
        'destinations', COALESCE(
            (SELECT jsonb_agg(jsonb_build_object('tcid', d.tcid, 'tuid', d.tuid, 'phone', d.phone, 'label', d.label)
                              ORDER BY d.tcid)
               FROM public.t_order_card_destinations(p_bot_key, o.rest_ref) d), '[]'::jsonb));
END $$;

-- ---------------------------------------------------------------------------------------------
-- 6. t_order_card_sent(...): record a copy that was just sent and take this chat's OLDER copies of the order.
--    One transaction. Returns jsonb {previous:[{id, tcid, message_id}], order_status} where order_status is the
--    order's status RIGHT NOW ('gone' if the order vanished): the "DB check after sending" (D24).
--    Idempotent on (bot_key, tcid, message_id).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_card_sent(
    p_bot_key text, p_tcid bigint, p_message_id bigint, p_tuid bigint,
    p_order_number text, p_order_type text, p_rest_ref text, p_card_status text)
RETURNS jsonb LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    v_id bigint;
    v_prev jsonb;
    o record;
BEGIN
    INSERT INTO public.t_sent_messages
           (bot_key, tcid, message_id, tuid, subject_type, subject_ref, order_type, kind, rest_ref, card_status)
    VALUES (p_bot_key, p_tcid, p_message_id, p_tuid, 'order', p_order_number, p_order_type, 'order_card', p_rest_ref, p_card_status)
    ON CONFLICT (bot_key, tcid, message_id) DO NOTHING
    RETURNING id INTO v_id;
    IF v_id IS NULL THEN
        SELECT m.id INTO v_id FROM public.t_sent_messages m
         WHERE m.bot_key = p_bot_key AND m.tcid = p_tcid AND m.message_id = p_message_id;
    END IF;

    WITH older AS (
        SELECT m.id FROM public.t_sent_messages m
         WHERE m.bot_key = p_bot_key AND m.tcid = p_tcid
           AND m.subject_type = 'order' AND m.subject_ref = p_order_number
           AND m.order_type IS NOT DISTINCT FROM p_order_type AND m.kind = 'order_card'
           AND m.state = 'live' AND m.id < v_id
         FOR UPDATE SKIP LOCKED
    ), taken AS (
        UPDATE public.t_sent_messages m
           SET state = 'taken', taken_for = 'delete', taken_at = now(), updated_at = now()
          FROM older WHERE m.id = older.id
        RETURNING m.id, m.tcid, m.message_id
    )
    SELECT COALESCE(jsonb_agg(jsonb_build_object('id', t.id, 'tcid', t.tcid, 'message_id', t.message_id)), '[]'::jsonb)
      INTO v_prev FROM taken t;

    SELECT * INTO o FROM public.t_order_card_row(p_order_number, p_order_type);
    RETURN jsonb_build_object(
        'previous', v_prev,
        'order_status', COALESCE(public.t_order_card_status(o.rcs, o.pickup_time), 'gone'));
END $$;

-- ---------------------------------------------------------------------------------------------
-- 7. t_order_cards_stale(bot_key, order_number?, order_type?): copies that need work (read-only).
--    A 'live' copy needs work when it shows a status other than the order's current one (or the order is gone)
--    or its chat is no longer a destination for the restaurant (invite revoked, admin removed, group unlinked).
--    A 'taken' copy needs work again when its claim is older than 30 seconds (the worker died, was cancelled by the 25 s webhook limit, or a Telegram call failed).
--    Both t_order_cards_take() and job_t_order_alerts() use this, so the sweep sees exactly what a refresh does.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_cards_stale(
    p_bot_key text, p_order_number text DEFAULT NULL, p_order_type text DEFAULT NULL)
RETURNS TABLE (id bigint, order_number text, order_type text, authorised boolean, viewer_phone text)
LANGUAGE sql STABLE SET search_path = public AS $$
    SELECT m.id, m.subject_ref, m.order_type, (d.tcid IS NOT NULL), d.phone
      FROM public.t_sent_messages m
      LEFT JOIN LATERAL (
            SELECT x.tcid, x.phone FROM public.t_order_card_destinations(m.bot_key, m.rest_ref) x
             WHERE x.tcid = m.tcid LIMIT 1) d ON true
      LEFT JOIN LATERAL public.t_order_card_row(m.subject_ref, m.order_type) r ON true
     WHERE m.bot_key = p_bot_key
       AND m.subject_type = 'order' AND m.kind = 'order_card' AND m.order_type IS NOT NULL
       AND (p_order_number IS NULL OR m.subject_ref = p_order_number)
       AND (p_order_type   IS NULL OR m.order_type  = p_order_type)
       AND (   (m.state = 'live'
                AND (m.card_status IS DISTINCT FROM COALESCE(public.t_order_card_status(r.rcs, r.pickup_time), 'gone')
                     OR d.tcid IS NULL))
            OR (m.state = 'taken' AND m.taken_at < now() - interval '30 seconds'))
$$;

-- ---------------------------------------------------------------------------------------------
-- 8. t_order_cards_take(bot_key, order_number, order_type): claim this order's stale copies for ONE refresh pass.
--    Returns jsonb {rows:[{id, tcid, message_id, tuid, viewer_phone, authorised, taken_for}]}.
--    Fresh claims are taken_for 'edit'; a re-offered claim keeps its taken_for ('delete' stays a delete).
--    FOR UPDATE SKIP LOCKED: two workers refreshing the same order never get the same copy.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_cards_take(p_bot_key text, p_order_number text, p_order_type text)
RETURNS jsonb LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    v_rows jsonb;
BEGIN
    WITH c AS (
        SELECT * FROM public.t_order_cards_stale(p_bot_key, p_order_number, p_order_type)
    ), locked AS (
        SELECT m.id FROM public.t_sent_messages m
         WHERE m.id IN (SELECT c.id FROM c)
           AND (m.state = 'live' OR (m.state = 'taken' AND m.taken_at < now() - interval '30 seconds'))
         FOR UPDATE SKIP LOCKED
    ), upd AS (
        UPDATE public.t_sent_messages m
           SET taken_for  = CASE WHEN m.state = 'taken' THEN m.taken_for ELSE 'edit' END,
               state      = 'taken',
               taken_at   = now(),
               updated_at = now()
          FROM locked WHERE m.id = locked.id
        RETURNING m.id, m.tcid, m.message_id, m.tuid, m.taken_for
    )
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'id', u.id, 'tcid', u.tcid, 'message_id', u.message_id, 'tuid', u.tuid,
               'viewer_phone', c.viewer_phone, 'authorised', c.authorised, 'taken_for', u.taken_for)
               ORDER BY u.id), '[]'::jsonb)
      INTO v_rows
      FROM upd u JOIN c ON c.id = u.id;
    RETURN jsonb_build_object('rows', v_rows);
END $$;

-- ---------------------------------------------------------------------------------------------
-- 9. t_order_card_mark(id, outcome, card_status, close): record what happened to a claimed copy.
--    outcome: 'edited' | 'deleted' | 'gone'. 'deleted' and 'gone' always close the row. 'edited' without
--    close returns the copy to 'live' showing p_card_status. Only a 'taken' row changes (idempotent).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_card_mark(p_id bigint, p_outcome text, p_card_status text, p_close boolean)
RETURNS void LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF p_outcome NOT IN ('edited', 'deleted', 'gone') THEN
        RAISE EXCEPTION 't_order_card_mark: bad outcome %', p_outcome;
    END IF;
    IF p_close OR p_outcome IN ('deleted', 'gone') THEN
        UPDATE public.t_sent_messages
           SET state = 'closed', close_reason = p_outcome, closed_at = now(), updated_at = now(),
               taken_for = NULL, card_status = COALESCE(p_card_status, card_status)
         WHERE id = p_id AND state = 'taken';
    ELSE
        UPDATE public.t_sent_messages
           SET state = 'live', card_status = p_card_status, taken_for = NULL, taken_at = NULL, updated_at = now()
         WHERE id = p_id AND state = 'taken';
    END IF;
END $$;

-- ---------------------------------------------------------------------------------------------
-- 10. Config rows (operator-editable; blank offsets = reminders off for that scope).
-- ---------------------------------------------------------------------------------------------
INSERT INTO public.ordelo_config (config_key, config_value, description) VALUES
 ('TGRAM_ORDER_ALERT_OFFSETS_SECS', '0,15,30,45',
  'Seconds after a new restaurant order at which the Telegram order card is (re)sent to linked admins. A restaurant can override with <REF>_TGRAM_ORDER_ALERT_OFFSETS_SECS. Blank = off.'),
 ('TGRAM_INBOX_RETENTION_DAYS', '7', 'Days t_inbox rows are kept by t_housekeeping().'),
 ('TGRAM_LEDGER_RETENTION_DAYS', '30', 'Days closed t_sent_messages rows and finished t_order_alerts rows are kept by t_housekeeping().')
ON CONFLICT (config_key) DO NOTHING;

-- ---------------------------------------------------------------------------------------------
-- 11. job_t_order_alerts(): the sweep. Structure follows dispatch/job_rider_pickup_alerts.sql.
--     Returns false when the POST failed (checkpoints stay pending), true otherwise.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_t_order_alerts()
RETURNS boolean LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    v_bot        constant text := 'rest_admin';
    v_reminders  jsonb;
    v_refreshes  jsonb;
    v_payload    jsonb;
    v_app_url    text;
    v_hook_url   text;
    v_resp       http_response;
BEGIN
    -- ---- SEED: one checkpoint per offset for each order still waiting for the restaurant ----------------
    INSERT INTO public.t_order_alerts (bot_key, order_number, order_type, rest_ref, offset_secs, n, of_n, due_at)
    SELECT v_bot, o.order_number, o.order_type, o.rest_ref, off.v, off.n::int, cardinality(cfg.arr),
           o.dtts + off.v * interval '1 second'
      FROM (SELECT s.order_number::text, 'delivery'::text AS order_type, s.rest_ref::text, s.dtts
              FROM public.delivery_summary s
             WHERE s.restaurant_confirmation_status = 'restaurant_unconfirmed' AND s.dtts > now() - interval '15 minutes'
            UNION ALL
            SELECT s.order_number::text, 'takeaway', s.rest_ref::text, s.dtts
              FROM public.takeaway_summary s
             WHERE s.restaurant_confirmation_status = 'restaurant_unconfirmed' AND s.dtts > now() - interval '15 minutes') o
     CROSS JOIN LATERAL (
            SELECT COALESCE(public.parse_alert_offsets(o.rest_ref || '_TGRAM_ORDER_ALERT_OFFSETS_SECS'),
                            public.parse_alert_offsets('TGRAM_ORDER_ALERT_OFFSETS_SECS')) AS arr) cfg
     CROSS JOIN LATERAL unnest(cfg.arr) WITH ORDINALITY AS off(v, n)
     WHERE EXISTS (SELECT 1 FROM public.t_order_card_destinations(v_bot, o.rest_ref))
    ON CONFLICT (bot_key, order_number, offset_secs) DO NOTHING;

    -- ---- CANCEL: the order was decided (any channel) before the reminder fell due ------------------------
    UPDATE public.t_order_alerts a
       SET status = 'cancelled', swept_at = now()
     WHERE a.status = 'pending' AND a.bot_key = v_bot
       AND NOT EXISTS (SELECT 1 FROM public.t_order_card_row(a.order_number, a.order_type) r
                        WHERE r.rcs = 'restaurant_unconfirmed');

    -- ---- DUE: one winner per order (largest offset: after an outage only the latest reminder is sent) ------
    SELECT jsonb_agg(jsonb_build_object('order_number', d.order_number, 'order_type', d.order_type,
                                        'n', d.n, 'of', d.of_n))
      INTO v_reminders
      FROM (SELECT a.*, row_number() OVER (PARTITION BY a.order_number, a.order_type ORDER BY a.offset_secs DESC) AS rn
              FROM public.t_order_alerts a
             WHERE a.status = 'pending' AND a.bot_key = v_bot AND a.due_at <= now()) d
     WHERE d.rn = 1;

    -- ---- STALE: orders with copies that no longer show the truth (WhatsApp accept, timeout, revoke ...) ----
    SELECT jsonb_agg(jsonb_build_object('order_number', s.order_number, 'order_type', s.order_type))
      INTO v_refreshes
      FROM (SELECT DISTINCT st.order_number, st.order_type
              FROM public.t_order_cards_stale(v_bot) st
             ORDER BY 1, 2 LIMIT 50) s;

    IF v_reminders IS NULL AND v_refreshes IS NULL THEN
        RETURN true;        -- nothing to say: the endpoint is not called at all
    END IF;

    -- ---- POST ---------------------------------------------------------------------------------------------
    v_payload := jsonb_build_object(
        'event_type', 't_order_alerts',
        'timestamp',  extract(epoch from now()),
        'reminders',  COALESCE(v_reminders, '[]'::jsonb),
        'refreshes',  COALESCE(v_refreshes, '[]'::jsonb));

    SELECT config_value INTO v_app_url FROM public.ordelo_config WHERE config_key = 'ORDELO_APP_URL';
    IF v_app_url IS NULL OR length(v_app_url) = 0 THEN
        v_app_url := 'https://agent.ordelo.app';
    END IF;
    IF right(v_app_url, 1) = '/' THEN
        v_app_url := left(v_app_url, length(v_app_url) - 1);
    END IF;
    v_hook_url := v_app_url || '/telegram/rest-admin/order-alerts';

    SELECT * INTO v_resp FROM http_post(v_hook_url, v_payload::text, 'application/json');
    IF v_resp.status IS NULL OR v_resp.status < 200 OR v_resp.status > 299 THEN
        RAISE NOTICE 'job_t_order_alerts: POST to % returned %, leaving checkpoints pending', v_hook_url, v_resp.status;
        RETURN false;
    END IF;

    -- ---- MARK, only on 2xx. ORDER MATTERS: supersede FIRST (see job_rider_pickup_alerts.sql): marking the
    --      winners 'sent' first would re-rank the survivors and leave a stale one to fire next tick.
    UPDATE public.t_order_alerts a
       SET status = 'superseded', swept_at = now()
      FROM (SELECT x.id, row_number() OVER (PARTITION BY x.order_number, x.order_type ORDER BY x.offset_secs DESC) AS rn
              FROM public.t_order_alerts x
             WHERE x.status = 'pending' AND x.bot_key = v_bot AND x.due_at <= now()) r
     WHERE a.id = r.id AND r.rn > 1;

    UPDATE public.t_order_alerts a
       SET status = 'sent', swept_at = now()
     WHERE a.status = 'pending' AND a.bot_key = v_bot AND a.due_at <= now();

    RETURN true;
END $$;

-- ---------------------------------------------------------------------------------------------
-- 12. t_housekeeping(): daily purge (D22). Returns jsonb counts. Retention comes from ordelo_config.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_housekeeping()
RETURNS jsonb LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    v_inbox_days  int;
    v_ledger_days int;
    n_inbox int; n_ledger int; n_alerts int;
BEGIN
    SELECT COALESCE((SELECT config_value::int FROM public.ordelo_config
                      WHERE config_key = 'TGRAM_INBOX_RETENTION_DAYS' AND config_value ~ '^\s*\d+\s*$'), 7)
      INTO v_inbox_days;
    SELECT COALESCE((SELECT config_value::int FROM public.ordelo_config
                      WHERE config_key = 'TGRAM_LEDGER_RETENTION_DAYS' AND config_value ~ '^\s*\d+\s*$'), 30)
      INTO v_ledger_days;

    DELETE FROM public.t_inbox WHERE received_at < now() - make_interval(days => v_inbox_days);
    GET DIAGNOSTICS n_inbox = ROW_COUNT;
    DELETE FROM public.t_sent_messages
     WHERE state = 'closed' AND closed_at < now() - make_interval(days => v_ledger_days);
    GET DIAGNOSTICS n_ledger = ROW_COUNT;
    DELETE FROM public.t_order_alerts
     WHERE status <> 'pending' AND created_at < now() - make_interval(days => v_ledger_days);
    GET DIAGNOSTICS n_alerts = ROW_COUNT;

    RETURN jsonb_build_object('t_inbox', n_inbox, 't_sent_messages', n_ledger, 't_order_alerts', n_alerts);
END $$;

-- ---------------------------------------------------------------------------------------------
-- Server-only objects: nobody but the service key may call them.
-- ---------------------------------------------------------------------------------------------
REVOKE ALL ON FUNCTION public.t_order_card_status(text, timestamptz) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.t_order_card_row(text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.t_order_card_destinations(text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.t_order_card_snapshot(text, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.t_order_card_sent(text, bigint, bigint, bigint, text, text, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.t_order_cards_stale(text, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.t_order_cards_take(text, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.t_order_card_mark(bigint, text, text, boolean) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.job_t_order_alerts() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.t_housekeeping() FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- OPERATOR SQL (run by hand after the code is deployed; commented out on purpose)
-- ---------------------------------------------------------------------------------------------
-- SELECT cron.schedule('job_t_order_alerts', '5 seconds', $$SELECT public.job_t_order_alerts()$$);
-- SELECT cron.schedule('t_housekeeping', '20 3 * * *', $$SELECT public.t_housekeeping()$$);
-- To stop:  SELECT cron.unschedule('job_t_order_alerts');
-- To inspect:  SELECT * FROM public.t_order_alerts ORDER BY id DESC LIMIT 20;
--              SELECT * FROM public.t_sent_messages ORDER BY id DESC LIMIT 20;
