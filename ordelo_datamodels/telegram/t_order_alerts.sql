-- =============================================================================================
-- ordelo_datamodels/telegram/t_order_alerts.sql
-- Telegram order cards: the reminder schedule (t_order_alerts), the card functions and the 5-second sweep.
-- =============================================================================================
-- LIVE CHECK    R6 t_alert_destinations(), t_order_card_snapshot() and job_t_order_alerts() verified live on 2026-10-22.
-- OBJECTS       table  t_order_alerts
--                   Reminder schedule: one row per order and offset (seconds after the order) with due time and status.
--               fn     t_order_card_status(p_rcs text, p_pickup timestamp with time zone) -> text
--                   Map an order's state to the card status key (awaiting, accepted, pickup_set, declined, auto_accepted, gone).
--               fn     t_order_card_row(p_order_number text, p_order_type text) -> TABLE(order_number text, order_type text, rest_ref text, rest_name text, dtts timestamp with time zone, rcs text, pickup_time timestamp with time zone, admin_phone text)
--                   Return the order's current state from delivery_summary or takeaway_summary as one row.
--               fn     t_order_card_destinations(p_bot_key text, p_rest_ref text) -> TABLE(tcid bigint, tuid bigint, phone text, label text)
--                   Return where cards for a restaurant go: the linked admins' chats (the one place that says so).
--               fn     t_alert_destinations(p_bot_key text, p_rest_ref text) -> TABLE(tcid bigint, tuid bigint, phone text, label text)
--                   t_order_card_destinations() without the admins who paused their alerts: where NEW cards, receipts and notices go.
--               fn     t_order_card_snapshot(p_bot_key text, p_order_number text, p_order_type text) -> jsonb
--                   Return everything needed to draw the card (order, items, status, destinations) in one read.
--               fn     t_order_cards_stale(p_bot_key text, p_order_number text, p_order_type text) -> TABLE(id bigint, order_number text, order_type text, authorised boolean, viewer_phone text)
--                   List orders whose sent copies show an old status or a revoked viewer (read-only).
--               fn     t_order_cards_take(p_bot_key text, p_order_number text, p_order_type text) -> jsonb
--                   Claim one order's stale copies for one refresh pass (state 'taken', SKIP LOCKED).
--               fn     job_t_order_alerts() -> boolean
--                   Every 5 seconds: seed, cancel, find due reminders and stale cards, POST them, and mark them on success.
-- REQUIRES      delivery/delivery_summary.sql
--               takeaway/takeaway_summary.sql
--               core/restaurant_master.sql
--               telegram/t_invites.sql
--               restaurant_admin/admin_roster.sql
--               telegram/t_sent_messages.sql
--               availability/pauses.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  Applying the file inserts TGRAM_ORDER_ALERT_OFFSETS_SECS if missing. The cron job POSTs every 5 s when something is due.
-- HOW IT FITS   Telegram order cards (D12, D14, D22, D24, D26): linked admins get the order card at configured offsets after the order
--                 arrives; each new copy replaces the previous one in that chat; every copy follows the order until it is final.
--                 The database is authoritative and is checked before every send; the ledger (t_sent_messages) only remembers what to tidy.
--                   pg_cron every 5 s -> job_t_order_alerts()
--                      SEED    delivery_summary + takeaway_summary rows still 'restaurant_unconfirmed' (< 15 min old) with at least one
--                              destination -> one t_order_alerts checkpoint per offset (TGRAM_ORDER_ALERT_OFFSETS_SECS, '0,15,30,45')
--                      CANCEL  pending checkpoints of orders no longer unconfirmed
--                      DUE     pending checkpoints with due_at <= now(); one winner per order (the largest offset)
--                      STALE   up to 50 orders with copies that show an old status or a revoked viewer
--                      POST    ORDELO_APP_URL/telegram/rest-admin/order-alerts {reminders, refreshes}
--                      MARK    only on a 2xx answer: superseded first, then winners 'sent'
--                   -> watomation/routers/telegram_order_alerts.py (background tasks)
--                      OrderCards.remind() -> snapshot -> send per destination -> t_order_card_sent -> delete old copies
--                      OrderCards.refresh() -> snapshot -> t_order_cards_take -> edit/delete -> t_order_card_mark
--                 Python: channels/telegram/rest_admin/order_cards/store.py CardStore.snapshot() / card_sent() / take_for_refresh() / mark().
--                 Pauses (R6, ADR 0013): NEW copies go to t_alert_destinations() (linked admins minus paused ones); whether a
--                 chat may SEE and TAP a card stays t_order_card_destinations(), so a paused admin's existing copies keep
--                 being refreshed and their buttons keep working.
--                 Card status keys MUST match channels/telegram/rest_admin/order_cards/model.py (Status):
--                   awaiting | accepted | pickup_set | declined | auto_accepted | gone
--                 Overview of the whole Telegram layer: docs/telegram-layer.md (and its HTML companion).
-- LIFECYCLE     t_order_alerts.status: pending -> sent | superseded | cancelled (order decided before the reminder was due).
-- CALLED BY     t_order_alerts:
--                 sql       job_t_order_alerts(), t_housekeeping()
--                 python    channels/telegram/rest_admin/order_cards/__init__.py (module-level SQL)
--                 python    watomation/routers/telegram_order_alerts.py (module-level SQL)
--               t_order_card_status:
--                 sql       t_order_card_sent() (telegram/t_sent_messages.sql)
--                 sql       t_order_card_snapshot() (telegram/t_order_alerts.sql)
--                 sql       t_order_cards_stale() (telegram/t_order_alerts.sql)
--               t_order_card_row:
--                 sql       job_t_order_alerts() (telegram/t_order_alerts.sql)
--                 sql       t_order_card_sent() (telegram/t_sent_messages.sql)
--                 sql       t_order_card_snapshot() (telegram/t_order_alerts.sql)
--                 sql       t_order_cards_stale() (telegram/t_order_alerts.sql)
--               t_order_card_destinations:
--                 sql       t_alert_destinations() (telegram/t_order_alerts.sql)
--                 sql       t_order_cards_stale() (telegram/t_order_alerts.sql)
--                 sql       t_receipts_stale() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--                 sql       t_admin_pause_chats() (telegram/t_admin_pauses.sql)
--               t_alert_destinations:
--                 sql       job_t_order_alerts() (telegram/t_order_alerts.sql)
--                 sql       t_notice_targets() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--                 sql       t_order_card_snapshot() (telegram/t_order_alerts.sql)
--                 sql       t_receipt_snapshot() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--               t_order_card_snapshot:
--                 python    channels/telegram/rest_admin/order_cards/store.py: CardStore.snapshot()
--               t_order_cards_stale:
--                 sql       job_t_order_alerts() (telegram/t_order_alerts.sql)
--                 sql       t_order_cards_take() (telegram/t_order_alerts.sql)
--               t_order_cards_take:
--                 python    channels/telegram/rest_admin/order_cards/store.py: CardStore.take_for_refresh()
--               job_t_order_alerts:
--                 cron      'job_t_order_alerts' 5 seconds
--                 python    watomation/routers/telegram_order_alerts.py (module-level SQL)
-- PYTHON MODEL  none
-- SECURITY      RLS ON with no policies; every function is revoked from PUBLIC/anon/authenticated: only the service key can call them.
--               Concurrency: up to 3 gunicorn workers may remind / refresh the same order; copies are claimed in SQL (state 'taken',
--                 FOR UPDATE SKIP LOCKED), a claim not finished in 30 s is offered again, and a newer copy only deletes OLDER ones (id <).
-- TESTS         tests/sql/test_order_cards_sql.py (loads this file into a throwaway Postgres)
--               tests/channels/telegram/test_order_card_store.py
--               tests/sql/test_order_cards_sql.py
--               tests/sql/test_order_test_script_sql.py
--               tests/sql/test_restaurant_notices_script_sql.py
--               tests/sql/test_restaurant_ready_adjust_notices_sql.py
--               tests/sql/test_admin_pauses_sql.py
--               tests/watomation/routers/test_telegram_order_alerts.py
-- GOTCHAS       Destinations are looked up by the summary's rest_ref (the order-number prefix): a restaurant whose orders use an alias
--                 prefix (config/params.py _REST_REF_ALIAS_MAP) gets no cards until the alias is resolved here.
--               Group chats (D27) would be a UNION ALL branch in t_order_card_destinations().
--               A per-restaurant <REF>_TGRAM_ORDER_ALERT_OFFSETS_SECS wins over the global offsets.
-- SEE ALSO      telegram/t_sent_messages.sql
--               telegram/t_housekeeping.sql
--               restaurant_admin/restaurant_order_decision.sql
--               restaurant_admin/restaurant_ready_adjust_notices.sql
--               docs/telegram-layer.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table t_order_alerts
--   Reminder schedule: one row per order and offset (seconds after the order) with due time and status.
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 1. Tables
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.t_order_alerts (
    id bigserial NOT NULL,
    bot_key text NOT NULL DEFAULT 'rest_admin' ::text,
    order_number text NOT NULL,
    order_type text NOT NULL,
    rest_ref text NOT NULL,
    offset_secs integer NOT NULL,
    n integer NOT NULL, -- 1-based position in the offset list ("reminder n of of_n")
    of_n integer NOT NULL,
    due_at timestamp with time zone NOT NULL, -- summary.dtts + offset
    status text NOT NULL DEFAULT 'pending' ::text,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    swept_at timestamp with time zone,
    CONSTRAINT t_order_alerts_pkey PRIMARY KEY (id),
    CONSTRAINT t_order_alerts_bot_key_order_number_offset_secs_key UNIQUE (bot_key, order_number, offset_secs),
    CONSTRAINT t_order_alerts_order_type_check CHECK ((order_type = ANY (ARRAY['delivery'::text, 'takeaway'::text]))),
    CONSTRAINT t_order_alerts_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'sent'::text, 'superseded'::text, 'cancelled'::text])))
);

CREATE INDEX IF NOT EXISTS t_order_alerts_due ON public.t_order_alerts USING btree (due_at)
WHERE (status = 'pending'::text);

ALTER TABLE public.t_order_alerts ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------------------------
-- function t_order_card_status(p_rcs text, p_pickup timestamp with time zone) -> text
--   Map an order's state to the card status key (awaiting, accepted, pickup_set, declined, auto_accepted, gone).
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 2. t_order_card_status(restaurant_confirmation_status, pickup_time): the card status key.
--    NULL in -> NULL out (no such order). 'restaurant_timedout' without a pickup is still 'awaiting': the
--    timeout handler sets the pickup within seconds. Same keys as model.py Status.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_card_status (p_rcs text, p_pickup timestamptz)
    RETURNS text
    LANGUAGE sql
    IMMUTABLE
    AS $$
    SELECT
        CASE WHEN p_rcs IS NULL THEN
            NULL
        WHEN p_rcs = 'restaurant_unconfirmed' THEN
            'awaiting'
        WHEN p_rcs IN ('restaurant_decline', 'auto_decline') THEN
            'declined'
        WHEN p_rcs IN ('restaurant_accept', 'restaurant_pickuptime_adjusted') THEN
            CASE WHEN p_pickup IS NULL THEN
                'accepted'
            ELSE
                'pickup_set'
        END
        WHEN p_rcs IN ('auto_accept', 'restaurant_timedout') THEN
            CASE WHEN p_pickup IS NULL THEN
                'awaiting'
            ELSE
                'auto_accepted'
        END
        ELSE
            'awaiting'
        END
$$;

-- ---------------------------------------------------------------------------------------------
-- Server-only objects: nobody but the service key may call them.
-- ---------------------------------------------------------------------------------------------
REVOKE ALL ON FUNCTION public.t_order_card_status (text, timestamptz) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_order_card_row(p_order_number text, p_order_type text) -> TABLE(order_number text, order_type text, rest_ref text, rest_name text, dtts timestamp with time zone, rcs text, pickup_time timestamp with time zone, admin_phone text)
--   Return the order's current state from delivery_summary or takeaway_summary as one row.
--   Data: reads delivery_summary, takeaway_summary.
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 3. t_order_card_row(order_number, order_type): the order's current state (0 or 1 row).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_card_row (p_order_number text, p_order_type text)
    RETURNS TABLE (
        order_number text,
        order_type text,
        rest_ref text,
        rest_name text,
        dtts timestamptz,
        rcs text,
        pickup_time timestamptz,
        admin_phone text)
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        s.order_number::text,
        'delivery'::text,
        s.rest_ref::text,
        s.rest_name::text,
        s.dtts,
        s.restaurant_confirmation_status::text,
        s.pickup_time,
        s.restaurant_admin::text
    FROM
        public.delivery_summary s
    WHERE
        p_order_type = 'delivery'
        AND s.order_number = p_order_number
    UNION ALL
    SELECT
        s.order_number::text,
        'takeaway'::text,
        s.rest_ref::text,
        s.rest_name::text,
        s.dtts,
        s.restaurant_confirmation_status::text,
        s.pickup_time,
        s.restaurant_admin::text
    FROM
        public.takeaway_summary s
    WHERE
        p_order_type = 'takeaway'
        AND s.order_number = p_order_number
$$;

REVOKE ALL ON FUNCTION public.t_order_card_row (text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_order_card_destinations(p_bot_key text, p_rest_ref text) -> TABLE(tcid bigint, tuid bigint, phone text, label text)
--   Return where cards for a restaurant go: the linked admins' chats (the one place that says so).
--   Data: reads admin_roster, restaurant_admin, t_invites (TRANSITION branch, P3 removes).
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 4. t_order_card_destinations(bot_key, rest_ref): WHERE cards for this restaurant go. The ONE place that says so.
--    Today: one private chat per admin on admin_roster who linked by sharing their phone (restaurant_admin), plus (TRANSITION,
--    P3 removes) admins with a claimed invite for the restaurant whose invite phone is on the list and who have no record. DISTINCT ON the chat so a person holding two invites
--    gets one card. Later (D27): UNION ALL linked group chats with tuid / phone NULL.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_card_destinations (p_bot_key text, p_rest_ref text)
    RETURNS TABLE (
        tcid bigint,
        tuid bigint,
        phone text,
        label text)
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT DISTINCT ON (x.tcid)
        x.tcid,
        x.tuid,
        x.phone,
        x.label
    FROM (
        SELECT
            r.tcid,
            r.tuid,
            r.phone,
            r.t_first_name AS label,
            1 AS pri,
            r.t_linked_at AS at
        FROM
            public.admin_roster r
        WHERE
            r.rest_ref = p_rest_ref
            AND r.tcid IS NOT NULL
        UNION ALL
        -- TRANSITION (P3 removes): claimed invites of listed phones that have no admin record yet
        SELECT
            i.telegram_chat_id,
            i.telegram_user_id,
            r.phone,
            i.telegram_first_name,
            2,
            i.claimed_at
        FROM
            public.t_invites i
            JOIN public.admin_roster r ON r.rest_ref = i.rest_ref
                AND r.phone = public.admin_phone_digits (i.phone_number)
        WHERE
            i.bot_key = p_bot_key
            AND i.rest_ref = p_rest_ref
            AND i.status = 'claimed'
            AND i.telegram_chat_id IS NOT NULL
            AND NOT EXISTS (
                SELECT
                    1
                FROM
                    public.restaurant_admin ra
                WHERE
                    ra.phone = r.phone)) x
    ORDER BY
        x.tcid,
        x.pri,
        x.at DESC NULLS LAST
$$;

REVOKE ALL ON FUNCTION public.t_order_card_destinations (text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_alert_destinations(p_bot_key text, p_rest_ref text) -> TABLE(tcid bigint, tuid bigint, phone text, label text)
--   t_order_card_destinations() without the admins who paused their alerts for this restaurant (is_paused('rest_admin',
--   phone, rest_ref), ADR 0013, phase R6): where NEW cards, receipts and notices go. Authorisation (who may see and tap)
--   stays t_order_card_destinations(). Admins whose record says channels without 'telegram' get nothing here (D6).
--   Data: reads restaurant_admin; calls is_paused(), t_order_card_destinations().
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_alert_destinations (p_bot_key text, p_rest_ref text)
    RETURNS TABLE (
        tcid bigint,
        tuid bigint,
        phone text,
        label text)
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        d.tcid,
        d.tuid,
        d.phone,
        d.label
    FROM
        public.t_order_card_destinations (p_bot_key, p_rest_ref) d
        LEFT JOIN public.restaurant_admin ra ON ra.phone = d.phone
    WHERE
        NOT public.is_paused ('rest_admin', d.phone, p_rest_ref)
        AND (ra.phone IS NULL -- TRANSITION (P3 removes): invite-only admins keep Telegram as today
            OR 'telegram' = ANY (ra.channels))
$$;

REVOKE ALL ON FUNCTION public.t_alert_destinations (text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_order_card_snapshot(p_bot_key text, p_order_number text, p_order_type text) -> jsonb
--   Return everything needed to draw the card (order, items, status, destinations) in one read.
--   Data: reads food_order, order_item; calls restaurant_admin_label(), t_alert_destinations(), t_order_card_row(), t_order_card_status().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 5. t_order_card_snapshot(bot_key, order_number, order_type): everything needed to draw the card.
--    NULL when the order does not exist. Returns jsonb
--      {status, rest_ref, facts:{order_number, order_type, rest_name, total, items[], ordered_at},
--       decided_by:{label, phone}|null, pickup_at, destinations:[{tcid, tuid, phone, label}]}
--    This is the "DB check before sending" (D24).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_card_snapshot (p_bot_key text, p_order_number text, p_order_type text)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public
    AS $$
DECLARE
    r public.food_order%ROWTYPE;
    o record;
    v_items jsonb;
    v_total text;
    v_phone text;
BEGIN
    SELECT
        * INTO o
    FROM
        public.t_order_card_row (p_order_number, p_order_type);
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    SELECT
        * INTO r
    FROM
        public.food_order f
    WHERE
        f.order_number = p_order_number;
    SELECT
        COALESCE(jsonb_agg(oi.quantity::text || 'x ' || oi.product_name ORDER BY oi.product_name), '[]'::jsonb) INTO v_items
    FROM
        public.order_item oi
    WHERE
        oi.order_id = r.order_id;
    v_total := CASE WHEN r.total_price IS NULL THEN
        ''
    ELSE
        '£' || to_char(r.total_price, 'FM999999990.00')
    END;
    v_phone := NULLIF (regexp_replace(COALESCE(o.admin_phone, ''), '\D', '', 'g'), '');
    RETURN jsonb_build_object('status', public.t_order_card_status (o.rcs, o.pickup_time), 'rest_ref', o.rest_ref, 'facts', jsonb_build_object('order_number', o.order_number, 'order_type', o.order_type, 'rest_name', o.rest_name, 'total', v_total, 'items', v_items, 'ordered_at', o.dtts), 'decided_by', CASE WHEN v_phone IS NULL THEN
            NULL
        ELSE
            jsonb_build_object('label', public.restaurant_admin_label (v_phone), 'phone', v_phone)
        END, 'pickup_at', o.pickup_time, 'destinations', COALESCE((
            SELECT
                jsonb_agg(jsonb_build_object('tcid', d.tcid, 'tuid', d.tuid, 'phone', d.phone, 'label', d.label)
            ORDER BY d.tcid)
            FROM public.t_alert_destinations (p_bot_key, o.rest_ref) d), '[]'::jsonb));
END
$$;

REVOKE ALL ON FUNCTION public.t_order_card_snapshot (text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_order_cards_stale(p_bot_key text, p_order_number text, p_order_type text) -> TABLE(id bigint, order_number text, order_type text, authorised boolean, viewer_phone text)
--   List orders whose sent copies show an old status or a revoked viewer (read-only).
--   Data: reads t_sent_messages; calls t_order_card_destinations(), t_order_card_row(), t_order_card_status().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 7. t_order_cards_stale(bot_key, order_number?, order_type?): copies that need work (read-only).
--    A 'live' copy needs work when it shows a status other than the order's current one (or the order is gone)
--    or its chat is no longer a destination for the restaurant (invite revoked, admin removed, group unlinked).
--    A 'taken' copy needs work again when its claim is older than 30 seconds (the worker died, was cancelled by the 25 s webhook limit, or a Telegram call failed).
--    Both t_order_cards_take() and job_t_order_alerts() use this, so the sweep sees exactly what a refresh does.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_cards_stale (p_bot_key text, p_order_number text DEFAULT NULL, p_order_type text DEFAULT NULL)
    RETURNS TABLE (
        id bigint,
        order_number text,
        order_type text,
        authorised boolean,
        viewer_phone text)
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        m.id,
        m.subject_ref,
        m.order_type,
        (d.tcid IS NOT NULL),
        d.phone
    FROM
        public.t_sent_messages m
    LEFT JOIN LATERAL (
        SELECT
            x.tcid,
            x.phone
        FROM
            public.t_order_card_destinations (m.bot_key, m.rest_ref) x
        WHERE
            x.tcid = m.tcid
        LIMIT 1) d ON TRUE
    LEFT JOIN LATERAL public.t_order_card_row (m.subject_ref, m.order_type) r ON TRUE
WHERE
    m.bot_key = p_bot_key
    AND m.subject_type = 'order'
    AND m.kind = 'order_card'
    AND m.order_type IS NOT NULL
    AND (p_order_number IS NULL
        OR m.subject_ref = p_order_number)
    AND (p_order_type IS NULL
        OR m.order_type = p_order_type)
    AND ((m.state = 'live'
            AND (m.card_status IS DISTINCT FROM COALESCE(public.t_order_card_status (r.rcs, r.pickup_time), 'gone')
                OR d.tcid IS NULL))
        OR (m.state = 'taken'
            AND m.taken_at < now() - interval '30 seconds'))
$$;

REVOKE ALL ON FUNCTION public.t_order_cards_stale (text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_order_cards_take(p_bot_key text, p_order_number text, p_order_type text) -> jsonb
--   Claim one order's stale copies for one refresh pass (state 'taken', SKIP LOCKED).
--   Data: writes t_sent_messages; calls t_order_cards_stale().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 8. t_order_cards_take(bot_key, order_number, order_type): claim this order's stale copies for ONE refresh pass.
--    Returns jsonb {rows:[{id, tcid, message_id, tuid, viewer_phone, authorised, taken_for}]}.
--    Fresh claims are taken_for 'edit'; a re-offered claim keeps its taken_for ('delete' stays a delete).
--    FOR UPDATE SKIP LOCKED: two workers refreshing the same order never get the same copy.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_cards_take (p_bot_key text, p_order_number text, p_order_type text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_rows jsonb;
BEGIN
    WITH c AS (
        SELECT
            *
        FROM
            public.t_order_cards_stale (p_bot_key, p_order_number, p_order_type)
),
LOCKED AS (
    SELECT
        m.id
    FROM
        public.t_sent_messages m
    WHERE
        m.id IN (
            SELECT
                c.id
            FROM
                c)
            AND (m.state = 'live'
                OR (m.state = 'taken'
                    AND m.taken_at < now() - interval '30 seconds'))
        FOR UPDATE
            SKIP LOCKED
),
upd AS (
    UPDATE
        public.t_sent_messages m
    SET
        taken_for = CASE WHEN m.state = 'taken' THEN
            m.taken_for
        ELSE
            'edit'
        END,
        state = 'taken',
        taken_at = now(),
        updated_at = now()
    FROM
        LOCKED
    WHERE
        m.id = locked.id
    RETURNING
        m.id,
        m.tcid,
        m.message_id,
        m.tuid,
        m.taken_for
)
SELECT
    COALESCE(jsonb_agg(jsonb_build_object('id', u.id, 'tcid', u.tcid, 'message_id', u.message_id, 'tuid', u.tuid, 'viewer_phone', c.viewer_phone, 'authorised', c.authorised, 'taken_for', u.taken_for)
        ORDER BY u.id), '[]'::jsonb) INTO v_rows
FROM
    upd u
    JOIN c ON c.id = u.id;
    RETURN jsonb_build_object('rows', v_rows);
END
$$;

REVOKE ALL ON FUNCTION public.t_order_cards_take (text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 10. Config rows (operator-editable; a blank global value = reminders off; a blank per-restaurant value = use the global one).
-- ---------------------------------------------------------------------------------------------
INSERT INTO public.ordelo_config (config_key, config_value, description)
    VALUES ('TGRAM_ORDER_ALERT_OFFSETS_SECS', '0,15,30,45', 'Seconds after a new restaurant order at which the Telegram order card is (re)sent to linked admins. A restaurant can override with <REF>_TGRAM_ORDER_ALERT_OFFSETS_SECS (blank there = use this global value; use 0 for a single card). Blank here = off.'),
    ('TGRAM_INBOX_RETENTION_DAYS', '7', 'Days t_inbox rows are kept by t_housekeeping().'),
    ('TGRAM_LEDGER_RETENTION_DAYS', '30', 'Days closed t_sent_messages rows and finished t_order_alerts rows are kept by t_housekeeping().')
ON CONFLICT (config_key)
    DO NOTHING;

-- ---------------------------------------------------------------------------------------------
-- function job_t_order_alerts() -> boolean
--   Every 5 seconds: seed, cancel, find due reminders and stale cards, POST them, and mark them on success.
--   Data: reads delivery_summary, ordelo_config, takeaway_summary; writes t_order_alerts; calls parse_alert_offsets(), t_alert_destinations(), t_order_card_row(), t_order_cards_stale().
--   HTTP: POST /telegram/rest-admin/order-alerts -> watomation/routers/telegram_order_alerts.py::order_alerts
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 11. job_t_order_alerts(): the sweep. Structure follows dispatch/job_rider_pickup_alerts.sql.
--     Returns false when the POST failed (checkpoints stay pending), true otherwise.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_t_order_alerts ()
    RETURNS boolean
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_bot constant text := 'rest_admin';
    v_reminders jsonb;
    v_refreshes jsonb;
    v_payload jsonb;
    v_app_url text;
    v_hook_url text;
    v_resp http_response;
BEGIN
    -- ---- SEED: one checkpoint per offset for each order still waiting for the restaurant ----------------
    INSERT INTO public.t_order_alerts (bot_key, order_number, order_type, rest_ref, offset_secs, n, of_n, due_at)
    SELECT
        v_bot,
        o.order_number,
        o.order_type,
        o.rest_ref,
        off.v,
        off.n::int,
        cardinality(cfg.arr),
        o.dtts + off.v * interval '1 second'
    FROM (
        SELECT
            s.order_number::text,
            'delivery'::text AS order_type,
            s.rest_ref::text,
            s.dtts
        FROM
            public.delivery_summary s
        WHERE
            s.restaurant_confirmation_status = 'restaurant_unconfirmed'
            AND s.dtts > now() - interval '15 minutes'
        UNION ALL
        SELECT
            s.order_number::text,
            'takeaway',
            s.rest_ref::text,
            s.dtts
        FROM
            public.takeaway_summary s
        WHERE
            s.restaurant_confirmation_status = 'restaurant_unconfirmed'
            AND s.dtts > now() - interval '15 minutes') o
    CROSS JOIN LATERAL (
        SELECT
            COALESCE(public.parse_alert_offsets (o.rest_ref || '_TGRAM_ORDER_ALERT_OFFSETS_SECS'), public.parse_alert_offsets ('TGRAM_ORDER_ALERT_OFFSETS_SECS')) AS arr) cfg
    CROSS JOIN LATERAL unnest(cfg.arr)
    WITH ORDINALITY AS off (v, n)
WHERE
    EXISTS (
        SELECT
            1
        FROM
            public.t_alert_destinations (v_bot, o.rest_ref))
ON CONFLICT (bot_key,
    order_number,
    offset_secs)
    DO NOTHING;
    -- ---- CANCEL: the order was decided (any channel) before the reminder fell due ------------------------
    UPDATE
        public.t_order_alerts a
    SET
        status = 'cancelled',
        swept_at = now()
    WHERE
        a.status = 'pending'
        AND a.bot_key = v_bot
        AND NOT EXISTS (
            SELECT
                1
            FROM
                public.t_order_card_row (a.order_number, a.order_type) r
            WHERE
                r.rcs = 'restaurant_unconfirmed');
    -- ---- DUE: one winner per order (largest offset: after an outage only the latest reminder is sent) ------
    SELECT
        jsonb_agg(jsonb_build_object('order_number', d.order_number, 'order_type', d.order_type, 'n', d.n, 'of', d.of_n)) INTO v_reminders
    FROM (
        SELECT
            a.*,
            row_number() OVER (PARTITION BY a.order_number, a.order_type ORDER BY a.offset_secs DESC) AS rn
        FROM
            public.t_order_alerts a
        WHERE
            a.status = 'pending'
            AND a.bot_key = v_bot
            AND a.due_at <= now()) d
WHERE
    d.rn = 1;
    -- ---- STALE: orders with copies that no longer show the truth (WhatsApp accept, timeout, revoke ...) ----
    SELECT
        jsonb_agg(jsonb_build_object('order_number', s.order_number, 'order_type', s.order_type)) INTO v_refreshes
    FROM ( SELECT DISTINCT
            st.order_number,
            st.order_type
        FROM
            public.t_order_cards_stale (v_bot) st
        ORDER BY
            1,
            2
        LIMIT 50) s;

    IF v_reminders IS NULL AND v_refreshes IS NULL THEN
        RETURN TRUE;
        -- nothing to say: the endpoint is not called at all
    END IF;
    -- ---- POST ---------------------------------------------------------------------------------------------
    v_payload := jsonb_build_object('event_type', 't_order_alerts', 'timestamp', extract(epoch FROM now()), 'reminders', COALESCE(v_reminders, '[]'::jsonb), 'refreshes', COALESCE(v_refreshes, '[]'::jsonb));

    SELECT
        config_value INTO v_app_url
    FROM
        public.ordelo_config
    WHERE
        config_key = 'ORDELO_APP_URL';
    IF v_app_url IS NULL OR length(v_app_url) = 0 THEN
        v_app_url := 'https://agent.ordelo.app';
    END IF;
    IF
    RIGHT (v_app_url,
    1) = '/' THEN
        v_app_url :=
    LEFT (v_app_url,
        length(v_app_url) - 1);
    END IF;
    v_hook_url := v_app_url || '/telegram/rest-admin/order-alerts';

    SELECT
        * INTO v_resp
    FROM
        http_post (v_hook_url, v_payload::text, 'application/json');
    IF v_resp.status IS NULL OR v_resp.status < 200 OR v_resp.status > 299 THEN
        RAISE NOTICE 'job_t_order_alerts: POST to % returned %, leaving checkpoints pending', v_hook_url, v_resp.status;
        RETURN FALSE;
    END IF;
    -- ---- MARK, only on 2xx. ORDER MATTERS: supersede FIRST (see job_rider_pickup_alerts.sql): marking the
    --      winners 'sent' first would re-rank the survivors and leave a stale one to fire next tick.
    UPDATE
        public.t_order_alerts a
    SET
        status = 'superseded',
        swept_at = now()
    FROM (
        SELECT
            x.id,
            row_number() OVER (PARTITION BY x.order_number, x.order_type ORDER BY x.offset_secs DESC) AS rn
        FROM
            public.t_order_alerts x
        WHERE
            x.status = 'pending'
            AND x.bot_key = v_bot
            AND x.due_at <= now()) r
WHERE
    a.id = r.id
        AND r.rn > 1;

    UPDATE
        public.t_order_alerts a
    SET
        status = 'sent',
        swept_at = now()
    WHERE
        a.status = 'pending'
        AND a.bot_key = v_bot
        AND a.due_at <= now();

    RETURN TRUE;
END
$$;

REVOKE ALL ON FUNCTION public.job_t_order_alerts () FROM PUBLIC, anon, authenticated;

-- pg_cron job 'job_t_order_alerts': runs every 5 seconds, active on live.
-- cron.schedule() with an existing job name updates that job in place, so re-running is safe.
-- SELECT
    -- cron.schedule ('job_t_order_alerts', '5 seconds', 'SELECT public.job_t_order_alerts()');

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.t_order_alerts IS 'Reminder schedule: one row per order and offset (seconds after the order) with due time and status.';

COMMENT ON FUNCTION public.t_order_card_status (p_rcs text, p_pickup timestamp with time zone) IS 'Map an order''s state to the card status key (awaiting, accepted, pickup_set, declined, auto_accepted, gone).';

COMMENT ON FUNCTION public.t_order_card_row (p_order_number text, p_order_type text) IS 'Return the order''s current state from delivery_summary or takeaway_summary as one row.';

COMMENT ON FUNCTION public.t_order_card_destinations (p_bot_key text, p_rest_ref text) IS 'Return where cards for a restaurant go: the linked admins'' chats (the one place that says so).';

COMMENT ON FUNCTION public.t_alert_destinations (p_bot_key text, p_rest_ref text) IS 't_order_card_destinations() without the admins who paused their alerts: where NEW cards, receipts and notices go.';

COMMENT ON FUNCTION public.t_order_card_snapshot (p_bot_key text, p_order_number text, p_order_type text) IS 'Return everything needed to draw the card (order, items, status, destinations) in one read.';

COMMENT ON FUNCTION public.t_order_cards_stale (p_bot_key text, p_order_number text, p_order_type text) IS 'List orders whose sent copies show an old status or a revoked viewer (read-only).';

COMMENT ON FUNCTION public.t_order_cards_take (p_bot_key text, p_order_number text, p_order_type text) IS 'Claim one order''s stale copies for one refresh pass (state ''taken'', SKIP LOCKED).';

COMMENT ON FUNCTION public.job_t_order_alerts () IS 'Every 5 seconds: seed, cancel, find due reminders and stale cards, POST them, and mark them on success.';

-- ---------------------------------------------------------------------------------------------
-- OPERATOR SQL (run by hand after the code is deployed; commented out on purpose)
-- ---------------------------------------------------------------------------------------------
-- SELECT cron.schedule('job_t_order_alerts', '5 seconds', $$SELECT public.job_t_order_alerts()$$);
-- SELECT cron.schedule('t_housekeeping', '20 3 * * *', $$SELECT public.t_housekeeping()$$);
-- To stop:  SELECT cron.unschedule('job_t_order_alerts');
-- To inspect:  SELECT * FROM public.t_order_alerts ORDER BY id DESC LIMIT 20;
--              SELECT * FROM public.t_sent_messages ORDER BY id DESC LIMIT 20;
