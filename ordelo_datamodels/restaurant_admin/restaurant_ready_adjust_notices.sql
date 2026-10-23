-- =============================================================================================
-- ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql
-- Kitchen actions shared by WhatsApp and Telegram (Ready, +10 / +20 pickup), Telegram kitchen receipts and plain notices.
-- =============================================================================================
-- LIVE CHECK    2026-10-23: t_receipt_snapshot() gained facts.accepted_by / accepted_at / accepted_auto (receipt progress flow,
--               plans/telegram-receipt-phases-plan.md D58): read-only, from existing columns; PENDING until the owner applies this file.
--               accepted_at is NULL once the pickup was moved (+10/+20 overwrite restaurant_update_dtts); "accepted by" is whoever
--               last set the pickup time. Python defaults the keys, so Python and SQL can deploy in either order.
--               R6 t_receipt_snapshot() and t_notice_targets() verified live on 2026-10-22 after the owner applied this file;
--               both now use t_alert_destinations() for new sends. Other objects were last compared on 2026-10-16.
-- OBJECTS       fn     restaurant_order_ready(p_order_number text, p_order_type text, p_admin_phone text, p_channel text) -> jsonb
--                   Ready, shared by every channel: record the first Ready tap per dispatch (delivery) or per order (takeaway).
--               fn     restaurant_order_adjust_pickup(p_order_number text, p_target timestamp with time zone, p_admin_phone text, p_channel text) -> jsonb
--                   Move a live delivery's pickup to p_target (+10 / +20 from the original); a no-op repeat writes nothing.
--               fn     t_order_ready(p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text) -> jsonb
--                   Telegram Ready: authorise the tapping person (D14), then restaurant_order_ready().
--               fn     t_order_adjust_pickup(p_bot_key text, p_tuid bigint, p_order_number text, p_minutes integer) -> jsonb
--                   Telegram +N: authorise, compute the target (original pickup + 10 or 20), then restaurant_order_adjust_pickup().
--               fn     t_receipt_status(p_order_number text, p_order_type text, p_dispatch_id integer) -> text
--                   Compute the receipt status key for an order from the database (gone, done, picked_up, ready@HH:MI, open@HH:MI, rider_cancelled).
--               fn     t_receipt_snapshot(p_bot_key text, p_order_number text, p_order_type text, p_dispatch_id integer) -> jsonb
--                   Return everything needed to draw one receipt, plus its destinations and reply targets, in one read.
--               fn     t_receipt_sent(p_bot_key text, p_tcid bigint, p_message_id bigint, p_tuid bigint, p_order_number text, p_order_type text, p_rest_ref text, p_dispatch_id integer, p_status text) -> jsonb
--                   Record a sent receipt copy and take OLDER receipt copies in that chat for deletion (D35).
--               fn     t_receipts_stale(p_bot_key text, p_order_number text, p_order_type text) -> TABLE(id bigint, order_number text, order_type text, dispatch_id integer, authorised boolean, viewer_phone text)
--                   List receipt copies whose status key no longer matches the database (read-only).
--               fn     t_receipts_take(p_bot_key text, p_order_number text, p_order_type text) -> jsonb
--                   Claim one order's stale receipt copies for one refresh pass (state 'taken').
--               fn     t_notice_targets(p_bot_key text, p_rest_ref text, p_order_number text, p_reply_kind text) -> TABLE(tcid bigint, tuid bigint, phone text, reply_to bigint)
--                   Return the destinations and reply target for a plain notice to a restaurant's Telegram admins (D36).
--               fn     t_notice_sent(p_bot_key text, p_tcid bigint, p_message_id bigint, p_tuid bigint, p_rest_ref text, p_order_number text, p_notice text) -> void
--                   Write an audit row for a sent notice, closed at once (nothing to edit or delete later).
--               fn     job_t_receipt_refresh() -> boolean
--                   Every 5 seconds: POST orders with stale receipt copies to /telegram/rest-admin/order-alerts (only when there are any).
-- REQUIRES      dispatch/delivery_dispatch.sql
--               dispatch/delivery_inflight.sql
--               delivery/delivery_summary.sql
--               takeaway/takeaway_summary.sql
--               telegram/t_order_alerts.sql
--               telegram/t_sent_messages.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none when applied (functions + cron). The cron job POSTs stale receipts to /telegram/rest-admin/order-alerts every 5 s.
-- HOW IT FITS   After a restaurant accepts and a rider takes the job, the kitchen gets one message (the receipt) with Ready, +10 and +20
--                 (plans/telegram-phase-7-8-kitchen-actions-and-notices.md, D28-D38). One rule for both channels, atomic:
--                   Ready: first tap per dispatch wins (ready_at / ready_by / ready_dispatch_id on delivery_summary; takeaway too).
--                   +N:    relative to the original pickup (pickup_time_initial); a repeat that changes nothing writes nothing. The UPDATE sets
--                          restaurant_confirmation_status 'restaurant_pickuptime_adjusted', so trigger_restaurant_updates POSTs and Python tells
--                          the rider; Ready changes no confirmation status, so no trigger fires and the follow-up is Python's.
--                 Gate (D31, same as ordelo/delivery_progress.check_delivery_progress): a delivery_inflight row exists and its dispatch is
--                 not 'pickedup' / 'completed'; takeaway: status 'pickup_confirmed'.
--                 Telegram receipts are t_sent_messages rows (kind 'receipt') that follow the database: a WhatsApp tap changes the receipt
--                 status key, job_t_receipt_refresh() (5 s) notices and every Telegram copy is edited. Plain notices (auto-accept, rider
--                 alerts, delivered, feedback) are recorded as kind 'notice' for audit.
--                 Pauses (R6): a NEW receipt or notice goes to t_alert_destinations() (telegram/t_order_alerts.sql), which leaves
--                 out admins who paused their alerts (/off on the restaurant bot); receipts already sent keep being refreshed and
--                 tapped (t_receipts_stale() still uses t_order_card_destinations()).
--                 Tables used: delivery_summary, takeaway_summary, delivery_inflight, delivery_dispatch, rider_master, restaurant_master,
--                 food_order / order_item (restaurant-agents), t_invites, t_sent_messages.
--                 Python: utils_common/order_management/restaurant_actions.py ready() / adjust_pickup() (WhatsApp and Telegram actors);
--                         channels/telegram/rest_admin/receipts/store.py ReceiptStore; channels/telegram/rest_admin/notices.py Notices;
--                         watomation/routers/telegram_order_alerts.py <- job_t_receipt_refresh().
-- LIFECYCLE     RESULT VOCABULARY (jsonb {result, ...})
--                 restaurant_order_ready:          ok | already_ready | not_ready_state | not_found
--                 restaurant_order_adjust_pickup:  ok | unchanged | not_ready_state | not_found
--                 t_order_ready / t_order_adjust_pickup: the same, plus not_authorised (checked right after not_found)
--               Receipt status keys (must match channels/telegram/rest_admin/receipts/model.py ReceiptStatus):
--                 delivery: gone | done | picked_up | ready@HH:MI | open@HH:MI | rider_cancelled ; takeaway: gone | done | ready@HH:MI | open@HH:MI
-- CALLED BY     restaurant_order_ready:
--                 sql       t_order_ready() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--                 python    utils_common/order_management/restaurant_actions.py: ready()
--               restaurant_order_adjust_pickup:
--                 sql       t_order_adjust_pickup() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--                 python    utils_common/order_management/restaurant_actions.py: adjust_pickup()
--               t_order_ready:
--                 python    utils_common/order_management/restaurant_actions.py: ready()
--               t_order_adjust_pickup:
--                 python    utils_common/order_management/restaurant_actions.py: adjust_pickup()
--               t_receipt_status:
--                 sql       t_receipt_sent() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--                 sql       t_receipt_snapshot() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--                 sql       t_receipts_stale() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--               t_receipt_snapshot:
--                 python    channels/telegram/rest_admin/receipts/store.py: ReceiptStore.snapshot()
--               t_receipt_sent:
--                 python    channels/telegram/rest_admin/receipts/store.py: ReceiptStore.receipt_sent()
--               t_receipts_stale:
--                 sql       job_t_receipt_refresh() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--                 sql       t_receipts_take() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--               t_receipts_take:
--                 python    channels/telegram/rest_admin/receipts/store.py: ReceiptStore.take_for_refresh()
--               t_notice_targets:
--                 python    channels/telegram/rest_admin/notices.py: NoticeStore.targets()
--               t_notice_sent:
--                 python    channels/telegram/rest_admin/notices.py: NoticeStore.notice_sent()
--               job_t_receipt_refresh:
--                 cron      'job_t_receipt_refresh' 5 seconds
--                 python    watomation/routers/telegram_order_alerts.py (module-level SQL)
-- PYTHON MODEL  none
-- SECURITY      Every function is revoked from PUBLIC/anon/authenticated: only the service key can call them.
--               Concurrency: one conditional UPDATE decides each tap; receipt copies are claimed in SQL (state 'taken', FOR UPDATE SKIP LOCKED);
--                 a claim not finished within 30 s is offered again; a newer receipt only deletes OLDER ones (id <).
-- TESTS         tests/sql/test_restaurant_ready_adjust_notices_sql.py (loads this file into a throwaway Postgres)
--               tests/sql/test_admin_pauses_sql.py
--               tests/channels/telegram/test_notices.py
--               tests/channels/telegram/test_receipts.py
--               tests/sql/test_restaurant_notices_script_sql.py
--               tests/sql/test_restaurant_ready_adjust_notices_sql.py
--               tests/utils_common/order_management/test_restaurant_actions.py
--               tests/watomation/test_on_callback_wa_handler.py
-- GOTCHAS       The kitchen columns live in delivery/delivery_summary.sql and takeaway/takeaway_summary.sql, and t_sent_messages.dispatch_id in
--                 telegram/t_sent_messages.sql (Gate 1 decision Q6). Re-running this file does not add them.
--               Not yet done: takeaway adjust-pickup; a takeaway 'completed' writer; group chats (D27); restaurants whose orders use an
--                 alias prefix (config/params.py _REST_REF_ALIAS_MAP).
-- SEE ALSO      restaurant_admin/restaurant_order_decision.sql
--               telegram/t_sent_messages.sql
--               telegram/t_order_alerts.sql
--               docs/telegram-layer.md
--               docs/live-order-test-harness.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function restaurant_order_ready(p_order_number text, p_order_type text, p_admin_phone text, p_channel text) -> jsonb
--   Ready, shared by every channel: record the first Ready tap per dispatch (delivery) or per order (takeaway).
--   Data: reads delivery_dispatch, delivery_inflight, food_order; writes delivery_summary, takeaway_summary; calls restaurant_admin_label().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 2. restaurant_order_ready(order_number, order_type, admin_phone, channel): Ready, shared by every channel.
--    p_channel: free text for logs ('whatsapp' | 'telegram' | 'manual'); not stored (a later ready_channel column is one line).
--    Delivery: only while a rider is on the job (D31) and only the FIRST tap per dispatch changes anything (D30, D35).
--    Takeaway: only an order whose pickup is confirmed and not yet ready.
--    Returns:
--      {result:'ok', rider_id, dispatch_id, rest_name, ready_by, ready_by_phone}                      delivery
--      {result:'ok', rest_name, customer_id, recipient, order_id, ready_by, ready_by_phone}           takeaway
--      {result:'already_ready', ready_at, ready_by, ready_by_phone}                                   lost the race / repeat tap
--      {result:'not_ready_state', progress:'not_in_progress'|'picked_up'}                             nothing to be ready for
--      {result:'not_found'}
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_order_ready (p_order_number text, p_order_type text, p_admin_phone text, p_channel text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_inf record;
    -- delivery_inflight + dispatch status (all NULL when no rider is on the job)
    v_cur record;
BEGIN
    IF p_order_type IS NULL OR p_order_type NOT IN ('delivery', 'takeaway') THEN
        RAISE EXCEPTION 'restaurant_order_ready: bad order type %', p_order_type;
    END IF;

    IF p_order_type = 'delivery' THEN
        SELECT
            i.dispatch_id,
            i.rider_id,
            d.status AS dispatch_status INTO v_inf
        FROM
            public.delivery_inflight i
            JOIN public.delivery_dispatch d ON d.dispatch_id = i.dispatch_id
        WHERE
            i.order_number = p_order_number FOR SHARE OF i, d;
        -- a pickup / cancel / re-dispatch writer waits for this call to commit (and vice versa)
        UPDATE
            public.delivery_summary s
        SET
            ready_at = now(),
            ready_by = p_admin_phone,
            ready_dispatch_id = v_inf.dispatch_id
        WHERE
            s.order_number = p_order_number
            AND v_inf.dispatch_id IS NOT NULL -- D31: a rider is on the job ...
            AND v_inf.dispatch_status NOT IN ('pickedup', 'completed') -- ... and has not collected yet
            AND s.ready_dispatch_id IS DISTINCT FROM v_inf.dispatch_id;
        -- first tap per dispatch wins (D30, D35)
        IF FOUND THEN
            RETURN jsonb_build_object('result', 'ok', 'rider_id', v_inf.rider_id, 'dispatch_id', v_inf.dispatch_id, 'rest_name', (
                    SELECT
                        rest_name
                    FROM public.delivery_summary
                    WHERE
                        order_number = p_order_number), 'ready_by', public.restaurant_admin_label (p_admin_phone), 'ready_by_phone', p_admin_phone);
        END IF;

        SELECT
            ready_at,
            ready_by,
            ready_dispatch_id INTO v_cur
        FROM
            public.delivery_summary
        WHERE
            order_number = p_order_number;
        IF NOT FOUND THEN
            RETURN jsonb_build_object('result', 'not_found');
        END IF;
        IF v_inf.dispatch_id IS NOT NULL AND v_cur.ready_dispatch_id = v_inf.dispatch_id AND v_inf.dispatch_status NOT IN ('pickedup', 'completed') THEN
            RETURN jsonb_build_object('result', 'already_ready', 'ready_at', v_cur.ready_at, 'ready_by', public.restaurant_admin_label (v_cur.ready_by), 'ready_by_phone', v_cur.ready_by);
        END IF;
        RETURN jsonb_build_object('result', 'not_ready_state', 'progress', CASE WHEN v_inf.dispatch_id IS NULL THEN
                'not_in_progress'
            ELSE
                'picked_up'
            END);
    END IF;
    -- takeaway
    UPDATE
        public.takeaway_summary
    SET
        ready_at = now(),
        ready_by = p_admin_phone
    WHERE
        order_number = p_order_number
        AND status = 'pickup_confirmed'
        AND ready_at IS NULL;
    IF FOUND THEN
        RETURN (
            SELECT
                jsonb_build_object('result', 'ok', 'rest_name', t.rest_name, 'customer_id', t.customer_id, 'recipient', f.recipient, 'order_id', f.order_id, 'ready_by', public.restaurant_admin_label (p_admin_phone), 'ready_by_phone', p_admin_phone)
            FROM
                public.takeaway_summary t
            LEFT JOIN public.food_order f ON f.order_number = t.order_number
        WHERE
            t.order_number = p_order_number);
    END IF;
    SELECT
        status,
        ready_at,
        ready_by INTO v_cur
    FROM
        public.takeaway_summary
    WHERE
        order_number = p_order_number;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    IF v_cur.ready_at IS NOT NULL THEN
        RETURN jsonb_build_object('result', 'already_ready', 'ready_at', v_cur.ready_at, 'ready_by', public.restaurant_admin_label (v_cur.ready_by), 'ready_by_phone', v_cur.ready_by);
    END IF;
    RETURN jsonb_build_object('result', 'not_ready_state', 'progress', 'not_in_progress');
END
$$;

-- ---------------------------------------------------------------------------------------------
-- Server-only objects: nobody but the service key may call them.
-- ---------------------------------------------------------------------------------------------
REVOKE ALL ON FUNCTION public.restaurant_order_ready (text, text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function restaurant_order_adjust_pickup(p_order_number text, p_target timestamp with time zone, p_admin_phone text, p_channel text) -> jsonb
--   Move a live delivery's pickup to p_target (+10 / +20 from the original); a no-op repeat writes nothing.
--   Data: reads delivery_dispatch, delivery_inflight; writes delivery_summary; calls restaurant_admin_label().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 3. restaurant_order_adjust_pickup(order_number, target, admin_phone, channel): +10/+20, delivery only (D32).
--    The target is an absolute time: WhatsApp's buttons carry one already; Telegram's wrapper computes it from
--    COALESCE(pickup_time_initial, pickup_time) + minutes, so repeated taps are never cumulative.
--    A target equal to the current pickup returns 'unchanged' and writes NOTHING (so no trigger, no rider message).
--    Otherwise one UPDATE: pickup_time_initial kept from the first adjust, restaurant_confirmation_status set to
--    'restaurant_pickuptime_adjusted' (this fires trigger_restaurant_updates, exactly as the WhatsApp handler did),
--    pickup_adjusted_by/at recorded. restaurant_admin (who accepted) is NOT overwritten.
--    Returns:
--      {result:'ok', pickup_time, by, by_phone}
--      {result:'unchanged', pickup_time}
--      {result:'not_ready_state', progress:'not_in_progress'|'picked_up'}      no rider on the job, or already collected
--      {result:'not_found'}
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_order_adjust_pickup (p_order_number text, p_target timestamptz, p_admin_phone text, p_channel text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_inf record;
    v_cur record;
BEGIN
    IF p_target IS NULL THEN
        RAISE EXCEPTION 'restaurant_order_adjust_pickup: missing target';
    END IF;
    SELECT
        i.dispatch_id,
        d.status AS dispatch_status INTO v_inf
    FROM
        public.delivery_inflight i
        JOIN public.delivery_dispatch d ON d.dispatch_id = i.dispatch_id
    WHERE
        i.order_number = p_order_number FOR SHARE OF i, d;
    -- the gate below stays true until this call commits (see restaurant_order_ready)
    SELECT
        pickup_time INTO v_cur
    FROM
        public.delivery_summary
    WHERE
        order_number = p_order_number
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    IF v_inf.dispatch_id IS NULL OR v_inf.dispatch_status IN ('pickedup', 'completed') THEN
        RETURN jsonb_build_object('result', 'not_ready_state', 'progress', CASE WHEN v_inf.dispatch_id IS NULL THEN
                'not_in_progress'
            ELSE
                'picked_up'
            END);
    END IF;
    IF v_cur.pickup_time = p_target THEN
        RETURN jsonb_build_object('result', 'unchanged', 'pickup_time', v_cur.pickup_time);
    END IF;
    UPDATE
        public.delivery_summary
    SET
        pickup_time_initial = COALESCE(pickup_time_initial, pickup_time),
        pickup_time = p_target,
        restaurant_confirmation_status = 'restaurant_pickuptime_adjusted',
        pickup_adjusted_by = p_admin_phone,
        pickup_adjusted_at = now(),
        restaurant_update_dtts = now()
    WHERE
        order_number = p_order_number;
    RETURN jsonb_build_object('result', 'ok', 'pickup_time', p_target, 'by', public.restaurant_admin_label (p_admin_phone), 'by_phone', p_admin_phone);
END
$$;

REVOKE ALL ON FUNCTION public.restaurant_order_adjust_pickup (text, timestamptz, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_order_ready(p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text) -> jsonb
--   Telegram Ready: authorise the tapping person (D14), then restaurant_order_ready().
--   Data: reads delivery_summary, takeaway_summary; calls restaurant_order_ready(), t_order_admin_phone().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 4. Telegram wrappers: authorise (D14) first, then call the shared function with the person's admin phone.
--    Same shape as t_order_decide / t_order_set_pickup (restaurant_order_decision.sql sections 6 and 7).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_ready (p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_rest_ref text;
    v_phone text;
BEGIN
    IF p_order_type = 'delivery' THEN
        SELECT
            rest_ref INTO v_rest_ref
        FROM
            public.delivery_summary
        WHERE
            order_number = p_order_number;
    ELSIF p_order_type = 'takeaway' THEN
        SELECT
            rest_ref INTO v_rest_ref
        FROM
            public.takeaway_summary
        WHERE
            order_number = p_order_number;
    ELSE
        RAISE EXCEPTION 't_order_ready: bad order type %', p_order_type;
    END IF;
    IF v_rest_ref IS NULL THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    v_phone := public.t_order_admin_phone (p_bot_key, p_tuid, v_rest_ref);
    IF v_phone IS NULL THEN
        RETURN jsonb_build_object('result', 'not_authorised');
    END IF;
    RETURN public.restaurant_order_ready (p_order_number, p_order_type, v_phone, 'telegram');
END
$$;

REVOKE ALL ON FUNCTION public.t_order_ready (text, bigint, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_order_adjust_pickup(p_bot_key text, p_tuid bigint, p_order_number text, p_minutes integer) -> jsonb
--   Telegram +N: authorise, compute the target (original pickup + 10 or 20), then restaurant_order_adjust_pickup().
--   Data: reads delivery_summary; calls restaurant_order_adjust_pickup(), t_order_admin_phone().
-- ---------------------------------------------------------------------------------------------
-- minutes must be 10 or 20; the target is COALESCE(pickup_time_initial, pickup_time) + minutes (delivery only).
CREATE OR REPLACE FUNCTION public.t_order_adjust_pickup (p_bot_key text, p_tuid bigint, p_order_number text, p_minutes int)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_rest_ref text;
    v_base timestamptz;
    v_phone text;
BEGIN
    IF p_minutes IS NULL OR p_minutes NOT IN (10, 20) THEN
        RAISE EXCEPTION 't_order_adjust_pickup: bad minutes %', p_minutes;
    END IF;
    SELECT
        rest_ref,
        COALESCE(pickup_time_initial, pickup_time) INTO v_rest_ref,
        v_base
    FROM
        public.delivery_summary
    WHERE
        order_number = p_order_number;
    IF v_rest_ref IS NULL THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    v_phone := public.t_order_admin_phone (p_bot_key, p_tuid, v_rest_ref);
    IF v_phone IS NULL THEN
        RETURN jsonb_build_object('result', 'not_authorised');
    END IF;
    IF v_base IS NULL THEN
        RETURN jsonb_build_object('result', 'not_ready_state', 'progress', 'not_in_progress');
    END IF;
    RETURN public.restaurant_order_adjust_pickup (p_order_number, v_base + make_interval(mins => p_minutes), v_phone, 'telegram');
END
$$;

REVOKE ALL ON FUNCTION public.t_order_adjust_pickup (text, bigint, text, int) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_receipt_status(p_order_number text, p_order_type text, p_dispatch_id integer) -> text
--   Compute the receipt status key for an order from the database (gone, done, picked_up, ready@HH:MI, open@HH:MI, rider_cancelled).
--   Data: reads delivery_dispatch, delivery_inflight, delivery_summary, takeaway_summary.
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 5. t_receipt_status(order_number, order_type, dispatch_id): the receipt status key (plan section 3.4).
--    Evaluated in this order. HH:MI is the pickup time in Europe/London, so a pickup change alone makes every copy stale.
--    delivery: gone | done | rider_cancelled | picked_up | ready@HH:MI | open@HH:MI
--    takeaway: gone | done | ready@HH:MI | open@HH:MI   (p_dispatch_id ignored)
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_receipt_status (p_order_number text, p_order_type text, p_dispatch_id integer)
    RETURNS text
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        CASE WHEN p_order_type = 'delivery' THEN
        (
            SELECT
                CASE WHEN s.order_number IS NULL
                    OR s.status = 'declined' THEN
                    'gone'
                WHEN s.status = 'completed' THEN
                    'done'
                WHEN i.dispatch_id IS NULL THEN
                    'rider_cancelled'
                WHEN d.status IN ('pickedup', 'completed') THEN
                    'picked_up'
                WHEN s.ready_dispatch_id = i.dispatch_id THEN
                    'ready@' || hm.v
                ELSE
                    'open@' || hm.v
                END
            FROM (
                SELECT
                    1) one
            LEFT JOIN public.delivery_summary s ON s.order_number = p_order_number
            LEFT JOIN public.delivery_inflight i ON i.order_number = p_order_number
                AND i.dispatch_id = p_dispatch_id
        LEFT JOIN public.delivery_dispatch d ON d.dispatch_id = i.dispatch_id
        CROSS JOIN LATERAL (
            SELECT
                COALESCE(to_char(s.pickup_time AT TIME ZONE 'Europe/London', 'HH24:MI'), '--:--') AS v) hm)
        WHEN p_order_type = 'takeaway' THEN
        (
            SELECT
                CASE WHEN t.order_number IS NULL
                    OR t.status = 'declined' THEN
                    'gone'
                WHEN t.status = 'completed' THEN
                    'done'
                WHEN t.ready_at IS NOT NULL THEN
                    'ready@' || hm.v
                ELSE
                    'open@' || hm.v
                END
            FROM (
                SELECT
                    1) one
        LEFT JOIN public.takeaway_summary t ON t.order_number = p_order_number
        CROSS JOIN LATERAL (
            SELECT
                COALESCE(to_char(t.pickup_time AT TIME ZONE 'Europe/London', 'HH24:MI'), '--:--') AS v) hm)
        ELSE
            NULL
        END
$$;

REVOKE ALL ON FUNCTION public.t_receipt_status (text, text, integer) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_receipt_snapshot(p_bot_key text, p_order_number text, p_order_type text, p_dispatch_id integer) -> jsonb
--   Return everything needed to draw one receipt, plus its destinations and reply targets, in one read.
--   Data: reads delivery_dispatch, delivery_inflight, delivery_summary, food_order, order_item, rider_master, t_sent_messages, takeaway_summary; calls restaurant_admin_label(), t_alert_destinations(), t_receipt_status().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 6. t_receipt_snapshot(bot_key, order_number, order_type, dispatch_id): everything needed to draw ONE receipt.
--    NULL when the order does not exist. For delivery, p_dispatch_id NULL means "the rider on the job now".
--    Returns jsonb
--      {status, rest_ref, dispatch_id,
--       facts:{order_number, order_type, rest_name, rest_code, pickup_at, pickup_initial, pickup_adjusted_by:{label,phone}|null,
--              ready_at, ready_by:{label,phone}|null, rider:{id,name}|null, customer:{address, phone}|null,
--              items:[{qty, name, line_total, mods[]}], small_order_fee, total, notes, pay_at_restaurant, completed_at},
--       destinations:[{tcid, tuid, phone, label, reply_to}]}      reply_to = message_id of the newest existing order-card copy in that chat
--    This is the "DB check before sending" (D24) for receipts.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_receipt_snapshot (p_bot_key text, p_order_number text, p_order_type text, p_dispatch_id integer)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public
    AS $$
DECLARE
    v_rest_ref text;
    v_rest_name text;
    v_code integer;
    v_pickup timestamptz;
    v_initial timestamptz;
    v_adj_by text;
    v_ready_at timestamptz;
    v_ready_by text;
    v_cust_addr text;
    v_cust_phone text;
    v_dispatch integer := p_dispatch_id;
    v_rider jsonb;
    v_completed timestamptz;
    f record;
    v_items jsonb;
    v_acc_by text;
    v_acc_at timestamptz;
    v_adj_at timestamptz;
    v_rcs text;
BEGIN
    IF p_order_type = 'delivery' THEN
        SELECT
            s.rest_ref,
            s.rest_name,
            s.rest_confirmation_code,
            s.pickup_time,
            s.pickup_time_initial,
            s.pickup_adjusted_by,
            s.ready_at,
            s.ready_by,
            s.customer_address,
            s.customer_id,
            s.restaurant_admin,
            s.restaurant_update_dtts,
            s.pickup_adjusted_at,
            s.restaurant_confirmation_status INTO v_rest_ref,
            v_rest_name,
            v_code,
            v_pickup,
            v_initial,
            v_adj_by,
            v_ready_at,
            v_ready_by,
            v_cust_addr,
            v_cust_phone,
            v_acc_by,
            v_acc_at,
            v_adj_at,
            v_rcs
        FROM
            public.delivery_summary s
        WHERE
            s.order_number = p_order_number;
        IF NOT FOUND THEN
            RETURN NULL;
        END IF;
        IF v_dispatch IS NULL THEN
            SELECT
                i.dispatch_id INTO v_dispatch
            FROM
                public.delivery_inflight i
            WHERE
                i.order_number = p_order_number;
        END IF;
        SELECT
            jsonb_build_object('id', d.rider_id, 'name', (
                    SELECT
                        m.rider_name
                    FROM public.rider_master m
                    WHERE
                        m.rider_id = d.rider_id LIMIT 1)) INTO v_rider
        FROM
            public.delivery_dispatch d
        WHERE
            d.dispatch_id = v_dispatch;
        SELECT
            max(d.status_update_dtts) INTO v_completed
        FROM
            public.delivery_dispatch d
        WHERE
            d.order_number = p_order_number
            AND d.status = 'completed';
    ELSIF p_order_type = 'takeaway' THEN
        SELECT
            s.rest_ref,
            s.rest_name,
            s.rest_confirmation_code,
            s.pickup_time,
            s.ready_at,
            s.ready_by,
            s.restaurant_admin,
            s.restaurant_update_dtts,
            s.restaurant_confirmation_status INTO v_rest_ref,
            v_rest_name,
            v_code,
            v_pickup,
            v_ready_at,
            v_ready_by,
            v_acc_by,
            v_acc_at,
            v_rcs
        FROM
            public.takeaway_summary s
        WHERE
            s.order_number = p_order_number;
        IF NOT FOUND THEN
            RETURN NULL;
        END IF;
    ELSE
        RAISE EXCEPTION 't_receipt_snapshot: bad order type %', p_order_type;
    END IF;

    SELECT
        * INTO f
    FROM
        public.food_order fo
    WHERE
        fo.order_number = p_order_number;
    SELECT
        COALESCE(jsonb_agg(jsonb_build_object('qty', oi.quantity, 'name', oi.product_name, 'line_total', round((COALESCE(oi.price, 0) * oi.quantity)::numeric, 2), 'mods', COALESCE(to_jsonb (oi.modifications), '[]'::jsonb))
        ORDER BY oi.ctid), '[]'::jsonb) INTO v_items
    FROM
        public.order_item oi
    WHERE
        oi.order_id = f.order_id;

    RETURN jsonb_build_object('status', public.t_receipt_status (p_order_number, p_order_type, v_dispatch), 'rest_ref', v_rest_ref, 'dispatch_id', v_dispatch, 'facts', jsonb_build_object('order_number', p_order_number, 'order_type', p_order_type, 'rest_name', v_rest_name, 'rest_code', v_code, 'pickup_at', v_pickup, 'pickup_initial', v_initial, 'pickup_adjusted_by', CASE WHEN v_adj_by IS NULL THEN
                NULL
            ELSE
                jsonb_build_object('label', public.restaurant_admin_label (v_adj_by), 'phone', v_adj_by)
            END, 'ready_at', v_ready_at, 'ready_by', CASE WHEN v_ready_by IS NULL THEN
                NULL
            ELSE
                jsonb_build_object('label', public.restaurant_admin_label (v_ready_by), 'phone', v_ready_by)
            END, 'rider', v_rider, 'customer', CASE WHEN p_order_type = 'delivery' THEN
                jsonb_build_object('address', v_cust_addr, 'phone', v_cust_phone)
            ELSE
                NULL
            END, 'items', v_items, 'small_order_fee', f.small_order_fee, 'total', f.total_price, 'notes', f.notes, 'pay_at_restaurant', (p_order_type = 'takeaway'
                AND f.payment_status = 'pay_at_rest'), 'completed_at', v_completed, 'accepted_by', CASE WHEN v_acc_by IS NULL THEN
                NULL
            ELSE
                jsonb_build_object('label', public.restaurant_admin_label (v_acc_by), 'phone', v_acc_by)
            END, 'accepted_at', CASE WHEN v_adj_at IS NULL THEN
                v_acc_at
            END, 'accepted_auto', COALESCE(v_rcs = 'auto_accept', FALSE)), 'destinations', COALESCE((
            SELECT
                jsonb_agg(jsonb_build_object('tcid', d.tcid, 'tuid', d.tuid, 'phone', d.phone, 'label', d.label, 'reply_to', (
                            SELECT
                                m.message_id
                            FROM public.t_sent_messages m
                            WHERE
                                m.bot_key = p_bot_key
                                AND m.tcid = d.tcid
                                AND m.subject_type = 'order'
                                AND m.subject_ref = p_order_number
                                AND m.kind = 'order_card'
                                AND (m.state <> 'closed'
                                    OR m.close_reason = 'edited')
                        ORDER BY m.id DESC LIMIT 1))
        ORDER BY d.tcid)
        FROM public.t_alert_destinations (p_bot_key, v_rest_ref) d), '[]'::jsonb));
END
$$;

REVOKE ALL ON FUNCTION public.t_receipt_snapshot (text, text, text, integer) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_receipt_sent(p_bot_key text, p_tcid bigint, p_message_id bigint, p_tuid bigint, p_order_number text, p_order_type text, p_rest_ref text, p_dispatch_id integer, p_status text) -> jsonb
--   Record a sent receipt copy and take OLDER receipt copies in that chat for deletion (D35).
--   Data: writes t_sent_messages; calls t_receipt_status().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 7. t_receipt_sent(...): record a receipt copy that was just sent and take this chat's OLDER receipt copies of the
--    order for deletion (D35: a new rider's receipt replaces the previous rider's). One transaction. Idempotent on
--    (bot_key, tcid, message_id). Returns jsonb {previous:[{id, tcid, message_id}], status} where status is the
--    receipt status RIGHT NOW for this dispatch ('gone' if the order vanished): the "DB check after sending".
--    Mirrors t_order_card_sent() (telegram/t_sent_messages.sql).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_receipt_sent (p_bot_key text, p_tcid bigint, p_message_id bigint, p_tuid bigint, p_order_number text, p_order_type text, p_rest_ref text, p_dispatch_id integer, p_status text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_id bigint;
    v_prev jsonb;
    v_status text := COALESCE(public.t_receipt_status (p_order_number, p_order_type, p_dispatch_id), 'gone');
BEGIN
    INSERT INTO public.t_sent_messages (bot_key, tcid, message_id, tuid, subject_type, subject_ref, order_type, kind, rest_ref, card_status, dispatch_id)
        VALUES (p_bot_key, p_tcid, p_message_id, p_tuid, 'order', p_order_number, p_order_type, 'receipt', p_rest_ref, p_status, p_dispatch_id)
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
            AND m.kind = 'receipt'
            -- still in the chat: live, or closed after its last edit (e.g. "this rider is no longer on the job")
            AND (m.state = 'live'
                OR (m.state = 'closed'
                    AND m.close_reason = 'edited'))
            AND m.id < v_id
            -- a late event for an old rider (or a vanished order) must never replace the current rider's receipt
            AND v_status NOT IN ('rider_cancelled', 'gone')
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

    RETURN jsonb_build_object('previous', v_prev, 'status', v_status);
END
$$;

REVOKE ALL ON FUNCTION public.t_receipt_sent (text, bigint, bigint, bigint, text, text, text, integer, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_receipts_stale(p_bot_key text, p_order_number text, p_order_type text) -> TABLE(id bigint, order_number text, order_type text, dispatch_id integer, authorised boolean, viewer_phone text)
--   List receipt copies whose status key no longer matches the database (read-only).
--   Data: reads t_sent_messages; calls t_order_card_destinations(), t_receipt_status().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 8. t_receipts_stale(bot_key, order_number?, order_type?): receipt copies that need work (read-only).
--    A 'live' copy needs work when its key differs from the database or its chat is no longer a destination (invite
--    revoked, admin removed). A 'taken' copy needs work again when its claim is older than 30 seconds.
--    Only copies sent in the last 3 days are looked at, so the 5-second job never scans an ever-growing ledger.
--    Both t_receipts_take() and job_t_receipt_refresh() use this, so the job sees exactly what a refresh does.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_receipts_stale (p_bot_key text, p_order_number text DEFAULT NULL, p_order_type text DEFAULT NULL)
    RETURNS TABLE (
        id bigint,
        order_number text,
        order_type text,
        dispatch_id integer,
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
        m.dispatch_id,
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
WHERE
    m.bot_key = p_bot_key
    AND m.subject_type = 'order'
    AND m.kind = 'receipt'
    AND m.order_type IS NOT NULL
    AND m.sent_at > now() - interval '3 days' -- a receipt nobody can act on any more is left as it is (bounded scan)
    AND (p_order_number IS NULL
        OR m.subject_ref = p_order_number)
    AND (p_order_type IS NULL
        OR m.order_type = p_order_type)
    AND ((m.state = 'live'
            AND (m.card_status IS DISTINCT FROM COALESCE(public.t_receipt_status (m.subject_ref, m.order_type, m.dispatch_id), 'gone')
                OR d.tcid IS NULL))
        OR (m.state = 'taken'
            AND m.taken_at < now() - interval '30 seconds'))
$$;

REVOKE ALL ON FUNCTION public.t_receipts_stale (text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_receipts_take(p_bot_key text, p_order_number text, p_order_type text) -> jsonb
--   Claim one order's stale receipt copies for one refresh pass (state 'taken').
--   Data: writes t_sent_messages; calls t_receipts_stale().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 9. t_receipts_take(bot_key, order_number, order_type): claim this order's stale receipt copies for ONE refresh pass.
--    Returns jsonb {rows:[{id, tcid, message_id, tuid, dispatch_id, viewer_phone, authorised, taken_for}]}.
--    Fresh claims are taken_for 'edit'; a re-offered claim keeps its taken_for. FOR UPDATE SKIP LOCKED.
--    The outcome is recorded with t_order_card_mark() (telegram/t_sent_messages.sql).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_receipts_take (p_bot_key text, p_order_number text, p_order_type text)
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
            public.t_receipts_stale (p_bot_key, p_order_number, p_order_type)
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
        m.dispatch_id,
        m.taken_for
)
SELECT
    COALESCE(jsonb_agg(jsonb_build_object('id', u.id, 'tcid', u.tcid, 'message_id', u.message_id, 'tuid', u.tuid, 'dispatch_id', u.dispatch_id, 'viewer_phone', c.viewer_phone, 'authorised', c.authorised, 'taken_for', u.taken_for)
        ORDER BY u.id), '[]'::jsonb) INTO v_rows
FROM
    upd u
    JOIN c ON c.id = u.id;
    RETURN jsonb_build_object('rows', v_rows);
END
$$;

REVOKE ALL ON FUNCTION public.t_receipts_take (text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_notice_targets(p_bot_key text, p_rest_ref text, p_order_number text, p_reply_kind text) -> TABLE(tcid bigint, tuid bigint, phone text, reply_to bigint)
--   Return the destinations and reply target for a plain notice to a restaurant's Telegram admins (D36).
--   Data: reads t_sent_messages; calls t_alert_destinations().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 10. Plain notices (D36). t_notice_targets(bot_key, rest_ref, order_number, reply_kind): where a notice goes
--     (the same destinations as order cards) and which message to reply to: the newest existing copy in that chat of
--     the order's card ('card'), the order's receipt ('receipt'), or none ('none'; order_number may be NULL).
--     reply_to is NULL when there is nothing to reply to; the sender must use allow_sending_without_reply.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_notice_targets (p_bot_key text, p_rest_ref text, p_order_number text, p_reply_kind text)
    RETURNS TABLE (
        tcid bigint,
        tuid bigint,
        phone text,
        reply_to bigint)
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        d.tcid,
        d.tuid,
        d.phone,
        CASE WHEN p_reply_kind IN ('card', 'receipt')
            AND p_order_number IS NOT NULL THEN
            (
                SELECT
                    m.message_id
                FROM
                    public.t_sent_messages m
                WHERE
                    m.bot_key = p_bot_key
                    AND m.tcid = d.tcid
                    AND m.subject_type = 'order'
                    AND m.subject_ref = p_order_number
                    AND m.kind = CASE p_reply_kind
                    WHEN 'card' THEN
                        'order_card'
                    ELSE
                        'receipt'
                END
                AND (m.state <> 'closed'
                    OR m.close_reason = 'edited')
            ORDER BY
                m.id DESC
            LIMIT 1)
        END
    FROM
        public.t_alert_destinations (p_bot_key, p_rest_ref) d
$$;

REVOKE ALL ON FUNCTION public.t_notice_targets (text, text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_notice_sent(p_bot_key text, p_tcid bigint, p_message_id bigint, p_tuid bigint, p_rest_ref text, p_order_number text, p_notice text) -> void
--   Write an audit row for a sent notice, closed at once (nothing to edit or delete later).
--   Data: writes t_sent_messages.
-- ---------------------------------------------------------------------------------------------
-- t_notice_sent: audit row for a notice copy, closed at once (nothing to edit or delete). Purged by t_housekeeping().
-- subject_type 'order' with the order number, or 'rest' with the restaurant ref for a notice that has no order.
CREATE OR REPLACE FUNCTION public.t_notice_sent (p_bot_key text, p_tcid bigint, p_message_id bigint, p_tuid bigint, p_rest_ref text, p_order_number text, p_notice text)
    RETURNS void
    LANGUAGE sql
    SET search_path = public
    AS $$
    INSERT INTO public.t_sent_messages (bot_key, tcid, message_id, tuid, subject_type, subject_ref, kind, rest_ref, card_status, state, close_reason, closed_at)
        VALUES (p_bot_key, p_tcid, p_message_id, p_tuid, CASE WHEN p_order_number IS NULL THEN
                'rest'
            ELSE
                'order'
            END, COALESCE(p_order_number, p_rest_ref), 'notice', p_rest_ref, p_notice, 'closed', 'sent', now())
    ON CONFLICT (bot_key, tcid, message_id)
        DO NOTHING
$$;

REVOKE ALL ON FUNCTION public.t_notice_sent (text, bigint, bigint, bigint, text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function job_t_receipt_refresh() -> boolean
--   Every 5 seconds: POST orders with stale receipt copies to /telegram/rest-admin/order-alerts (only when there are any).
--   Data: reads ordelo_config; calls t_receipts_stale().
--   HTTP: POST /telegram/rest-admin/order-alerts -> watomation/routers/telegram_order_alerts.py::order_alerts
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 11. job_t_receipt_refresh(): the receipt sweep, every 5 seconds. Structure follows job_t_order_alerts()
--     (telegram/t_order_alerts.sql) but has no schedule table: staleness is the whole signal.
--     Up to 50 orders with stale receipt copies are POSTed; the app edits the copies (silently) and marks them.
--     Nothing stale -> the endpoint is not called. Returns false when the POST failed; the next tick finds the same
--     copies stale again, so nothing needs marking here.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_t_receipt_refresh ()
    RETURNS boolean
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_bot constant text := 'rest_admin';
    v_receipts jsonb;
    v_app_url text;
    v_hook_url text;
    v_resp http_response;
BEGIN
    SELECT
        jsonb_agg(jsonb_build_object('order_number', s.order_number, 'order_type', s.order_type)) INTO v_receipts
    FROM ( SELECT DISTINCT
            st.order_number,
            st.order_type
        FROM
            public.t_receipts_stale (v_bot) st
        ORDER BY
            1,
            2
        LIMIT 50) s;
    IF v_receipts IS NULL THEN
        RETURN TRUE;
    END IF;

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
        http_post (v_hook_url, jsonb_build_object('event_type', 't_receipt_refresh', 'timestamp', extract(epoch FROM now()), 'receipts', v_receipts)::text, 'application/json');
    IF v_resp.status IS NULL OR v_resp.status < 200 OR v_resp.status > 299 THEN
        RAISE NOTICE 'job_t_receipt_refresh: POST to % returned %', v_hook_url, v_resp.status;
        RETURN FALSE;
    END IF;
    RETURN TRUE;
END
$$;

REVOKE ALL ON FUNCTION public.job_t_receipt_refresh () FROM PUBLIC, anon, authenticated;

-- pg_cron job 'job_t_receipt_refresh': runs every 5 seconds, active on live.
-- cron.schedule() with an existing job name updates that job in place, so re-running is safe.
SELECT
    cron.schedule ('job_t_receipt_refresh', '5 seconds', 'SELECT public.job_t_receipt_refresh()');

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.restaurant_order_ready (p_order_number text, p_order_type text, p_admin_phone text, p_channel text) IS 'Ready, shared by every channel: record the first Ready tap per dispatch (delivery) or per order (takeaway).';

COMMENT ON FUNCTION public.restaurant_order_adjust_pickup (p_order_number text, p_target timestamp with time zone, p_admin_phone text, p_channel text) IS 'Move a live delivery''s pickup to p_target (+10 / +20 from the original); a no-op repeat writes nothing.';

COMMENT ON FUNCTION public.t_order_ready (p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text) IS 'Telegram Ready: authorise the tapping person (D14), then restaurant_order_ready().';

COMMENT ON FUNCTION public.t_order_adjust_pickup (p_bot_key text, p_tuid bigint, p_order_number text, p_minutes integer) IS 'Telegram +N: authorise, compute the target (original pickup + 10 or 20), then restaurant_order_adjust_pickup().';

COMMENT ON FUNCTION public.t_receipt_status (p_order_number text, p_order_type text, p_dispatch_id integer) IS 'Compute the receipt status key for an order from the database (gone, done, picked_up, ready@HH:MI, open@HH:MI, rider_cancelled).';

COMMENT ON FUNCTION public.t_receipt_snapshot (p_bot_key text, p_order_number text, p_order_type text, p_dispatch_id integer) IS 'Return everything needed to draw one receipt, plus its destinations and reply targets, in one read.';

COMMENT ON FUNCTION public.t_receipt_sent (p_bot_key text, p_tcid bigint, p_message_id bigint, p_tuid bigint, p_order_number text, p_order_type text, p_rest_ref text, p_dispatch_id integer, p_status text) IS 'Record a sent receipt copy and take OLDER receipt copies in that chat for deletion (D35).';

COMMENT ON FUNCTION public.t_receipts_stale (p_bot_key text, p_order_number text, p_order_type text) IS 'List receipt copies whose status key no longer matches the database (read-only).';

COMMENT ON FUNCTION public.t_receipts_take (p_bot_key text, p_order_number text, p_order_type text) IS 'Claim one order''s stale receipt copies for one refresh pass (state ''taken'').';

COMMENT ON FUNCTION public.t_notice_targets (p_bot_key text, p_rest_ref text, p_order_number text, p_reply_kind text) IS 'Return the destinations and reply target for a plain notice to a restaurant''s Telegram admins (D36).';

COMMENT ON FUNCTION public.t_notice_sent (p_bot_key text, p_tcid bigint, p_message_id bigint, p_tuid bigint, p_rest_ref text, p_order_number text, p_notice text) IS 'Write an audit row for a sent notice, closed at once (nothing to edit or delete later).';

COMMENT ON FUNCTION public.job_t_receipt_refresh () IS 'Every 5 seconds: POST orders with stale receipt copies to /telegram/rest-admin/order-alerts (only when there are any).';

-- ---------------------------------------------------------------------------------------------
-- OPERATOR SQL (run by hand after the code is deployed; commented out on purpose)
-- ---------------------------------------------------------------------------------------------
-- SELECT cron.schedule('job_t_receipt_refresh', '5 seconds', $$SELECT public.job_t_receipt_refresh()$$);
-- To stop:  SELECT cron.unschedule('job_t_receipt_refresh');
-- Rollback of behaviour (no data loss): unschedule the job and redeploy the previous app build; the new columns are inert.
-- To inspect:  SELECT id, kind, subject_ref, dispatch_id, card_status, state FROM public.t_sent_messages
--               WHERE kind IN ('receipt', 'notice') ORDER BY id DESC LIMIT 20;
