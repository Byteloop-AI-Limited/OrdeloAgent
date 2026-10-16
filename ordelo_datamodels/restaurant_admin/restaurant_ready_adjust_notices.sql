-- =============================================================================================
-- Feature SQL: kitchen actions (Ready, adjust pickup) shared by WhatsApp and Telegram + Telegram kitchen receipts and notices
-- =============================================================================================
-- See also (paths under ordelo_datamodels/): sibling files: restaurant_admin/restaurant_order_decision.sql (accept / decline, run before this one), telegram/t_order_alerts.sql (order cards and the t_sent_messages ledger this file reuses), telegram/t_invites.sql (who is an admin).
-- Run once in the Supabase SQL editor (operator step; the implementing agent never runs it).
-- Repeatable: ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS / CREATE OR REPLACE. Nothing is dropped or rewritten.
-- Run it AFTER restaurant_order_decision.sql and create_t_order_alerts.sql (it reads restaurant_admin_label(),
-- t_order_admin_phone(), t_order_card_destinations(), t_order_card_mark(), t_sent_messages and the http extension).
-- Run it BEFORE deploying the code that calls it (utils_common/order_management/restaurant_actions.py,
-- channels/telegram/rest_admin/receipts/store.py, channels/telegram/rest_admin/notices.py).
-- !! This file ADDS COLUMNS to delivery_summary and takeaway_summary, so RE-RUN init_delivery.sql and init_takeaway.sql
--    straight after it (they now list their RETURNING columns; the old `RETURNING *` fails with SQLSTATE 42804
--    "structure of query does not match function result type" once the tables gain columns).
-- It never redefines a function owned by another file. Nothing is sent until the operator schedules
-- job_t_receipt_refresh (last section of this file).
--
-- WHAT THIS ADDS
--   Columns    delivery_summary.ready_at / ready_by / ready_dispatch_id      Ready, per dispatch (D30, D35)
--              delivery_summary.pickup_time_initial / pickup_adjusted_by / pickup_adjusted_at      +10/+20 bookkeeping (D32)
--              takeaway_summary.ready_at / ready_by
--              t_sent_messages.dispatch_id                                    receipts only: which rider's receipt a copy is
--   Functions  restaurant_order_ready()          Ready, shared by every channel; the first tap per dispatch wins (D30, D31)
--              restaurant_order_adjust_pickup()  +10/+20 relative to the original pickup; 'unchanged' writes nothing (D32)
--              t_order_ready()                   Telegram Ready: authorise (D14), then restaurant_order_ready()
--              t_order_adjust_pickup()           Telegram +N: authorise (D14), compute the target, then the shared function
--              t_receipt_status()                receipt status key from the database (plan section 3.4)
--              t_receipt_snapshot()              everything needed to draw one receipt + destinations + reply targets
--              t_receipt_sent()                  record a sent receipt copy, take OLDER receipt copies in that chat (D35)
--              t_receipts_stale()                receipt copies whose key differs from the database (read-only)
--              t_receipts_take()                 claim one order's stale receipt copies for one refresh pass
--              t_notice_targets()                destinations + reply target for a plain notice (D36)
--              t_notice_sent()                   audit row for a plain notice, closed at once (D36)
--              job_t_receipt_refresh()           5-second job: stale receipts -> POST /telegram/rest-admin/order-alerts
--   Ledger     t_sent_messages.kind now also holds 'receipt' (a live, editable copy) and 'notice' (audit only, closed at
--              once, close_reason 'sent'). kind is free text; create_t_order_alerts.sql's comment lists the values.
--
-- WHY (plans/telegram-phase-7-8-kitchen-actions-and-notices.md, decisions D28-D38)
--   After a restaurant accepts an order and a rider takes the job, the kitchen needs one message with everything on it
--   (the receipt) and three buttons: Ready (tell the rider the food is ready), +10 and +20 (move the pickup time).
--   WhatsApp already does this; Telegram must do the same at the same time, and both channels must follow ONE rule.
--   So the rule lives here, once, atomically (Ready: first tap per dispatch wins; +N: relative to the original pickup,
--   a repeat that changes nothing writes nothing). The rider/customer follow-up stays in Python
--   (utils_common/order_management/restaurant_actions.py), run only when the database says 'ok'.
--   Telegram receipts are ledger rows that follow the database: a WhatsApp tap changes the receipt status key, the
--   5-second job notices, and every Telegram copy is edited to match. Plain notices (auto-accept, rider alerts,
--   delivered, feedback) are sent to the same destinations and recorded for audit.
--
-- HOW THE PIECES FIT TOGETHER
--   Tables used (defined elsewhere): delivery_summary (delivery/delivery_summary.sql), takeaway_summary (takeaway/takeaway_summary.sql),
--     delivery_inflight (dispatch/delivery_inflight.sql), delivery_dispatch (dispatch/delivery_dispatch.sql), rider_master (core/restaurant_master.sql),
--     food_order / order_item (utils_common/order_management/food_order.sql), restaurant_master (core/restaurant_master.sql),
--     t_invites (create_t_invites.sql), t_sent_messages (create_t_order_alerts.sql).
--   Triggers (unchanged): trigger_restaurant_updates is AFTER UPDATE OF restaurant_confirmation_status, so the adjust
--     UPDATE (which sets it to 'restaurant_pickuptime_adjusted') still POSTs /delivery-hooks/restaurant-confirmation-request
--     -> _handle_restaurant_pickuptime_adjusted -> rider agent. 'unchanged' does no UPDATE, so no webhook fires.
--     Ready does NOT touch restaurant_confirmation_status: no trigger fires; the follow-up is Python's.
--   Gate rule (D31), the same as ordelo/delivery_progress.check_delivery_progress: a delivery_inflight row exists for the
--     order and its delivery_dispatch.status is not 'pickedup' / 'completed'. Takeaway: status = 'pickup_confirmed'.
--   Python callers (keep in sync with the module docstrings):
--     utils_common/order_management/restaurant_actions.py
--       ready(ref, WhatsAppActor)          -> restaurant_order_ready(p_order_number, p_order_type, p_admin_phone, p_channel)
--       ready(ref, TelegramActor)          -> t_order_ready(p_bot_key, p_tuid, p_order_number, p_order_type)
--       adjust_pickup(ref, WhatsAppActor)  -> restaurant_order_adjust_pickup(p_order_number, p_target, p_admin_phone, p_channel)
--       adjust_pickup(ref, TelegramActor)  -> t_order_adjust_pickup(p_bot_key, p_tuid, p_order_number, p_minutes)
--       callers: watomation/on_callback_wa_handler.py (admin_collection_ready, admin_takeaway_ready,
--                admin_adjust_pickup_time), channels/telegram/rest_admin/receipts/__init__.py (Receipts.tap)
--     channels/telegram/rest_admin/receipts/store.py (ReceiptStore)
--       snapshot()          -> t_receipt_snapshot(p_bot_key, p_order_number, p_order_type, p_dispatch_id)
--       receipt_sent()      -> t_receipt_sent(p_bot_key, p_tcid, p_message_id, p_tuid, p_order_number, p_order_type,
--                                             p_rest_ref, p_dispatch_id, p_status)
--       take_for_refresh()  -> t_receipts_take(p_bot_key, p_order_number, p_order_type)
--       mark()              -> t_order_card_mark(p_id, p_outcome, p_card_status, p_close)   (create_t_order_alerts.sql;
--                              generic on t_sent_messages.id, so receipts reuse it)
--     channels/telegram/rest_admin/notices.py (Notices)
--       targets()           -> t_notice_targets(p_bot_key, p_rest_ref, p_order_number, p_reply_kind)
--       notice_sent()       -> t_notice_sent(p_bot_key, p_tcid, p_message_id, p_tuid, p_rest_ref, p_order_number, p_notice)
--     watomation/routers/telegram_order_alerts.py  <- job_t_receipt_refresh() (pg_cron, POST {"receipts": [...]})
--     (t_receipt_status and t_receipts_stale are called only by the other functions here and by pg_cron.)
--   Receipt status keys MUST match channels/telegram/rest_admin/receipts/model.py (ReceiptStatus):
--       delivery: gone | done | picked_up | ready@HH:MI | open@HH:MI | rider_cancelled
--       takeaway: gone | done | ready@HH:MI | open@HH:MI       (HH:MI = pickup time in Europe/London)
--
-- RESULT VOCABULARY (jsonb {result, ...})
--   restaurant_order_ready:          ok | already_ready | not_ready_state | not_found
--   restaurant_order_adjust_pickup:  ok | unchanged | not_ready_state | not_found
--   t_order_ready / t_order_adjust_pickup: the same, plus not_authorised (checked right after not_found)
--   Bad arguments (unknown order type, minutes other than 10 or 20, missing target) RAISE: a programming error.
--
-- CONCURRENCY   One conditional UPDATE decides each tap; two channels, two admins or three workers cannot both win.
--               Receipt copies are claimed in SQL (state 'taken', FOR UPDATE SKIP LOCKED); a claim not finished within
--               30 seconds is offered again. A newer receipt only deletes OLDER ones (id <).
-- SECURITY      RLS on t_sent_messages unchanged; every function is REVOKEd from PUBLIC, anon, authenticated:
--               only the service key (client_ordelo_service) can call them. The shared functions trust p_admin_phone;
--               the t_ wrappers authorise first (t_order_admin_phone: claimed invite + phone in restaurant_master.admins).
-- NOT YET DONE  * takeaway adjust-pickup; a takeaway 'completed' writer (the receipt stays 'ready' until something sets it).
--               * group chats (D27): extend t_order_card_destinations() with a UNION ALL branch; receipts follow.
--               * restaurants whose orders use an alias prefix (config/params.py _REST_REF_ALIAS_MAP), as for order cards.
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. Columns. Nullable, no defaults: no table rewrite, only a catalog update.
-- ---------------------------------------------------------------------------------------------
-- (The statement that followed this comment is now generated from live in delivery/delivery_summary.sql.)

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
            s.customer_id INTO v_rest_ref,
            v_rest_name,
            v_code,
            v_pickup,
            v_initial,
            v_adj_by,
            v_ready_at,
            v_ready_by,
            v_cust_addr,
            v_cust_phone
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
            s.ready_by INTO v_rest_ref,
            v_rest_name,
            v_code,
            v_pickup,
            v_ready_at,
            v_ready_by
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
                AND f.payment_status = 'pay_at_rest'), 'completed_at', v_completed), 'destinations', COALESCE((
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
        FROM public.t_order_card_destinations (p_bot_key, v_rest_ref) d), '[]'::jsonb));
END
$$;

REVOKE ALL ON FUNCTION public.t_receipt_snapshot (text, text, text, integer) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- 7. t_receipt_sent(...): record a receipt copy that was just sent and take this chat's OLDER receipt copies of the
--    order for deletion (D35: a new rider's receipt replaces the previous rider's). One transaction. Idempotent on
--    (bot_key, tcid, message_id). Returns jsonb {previous:[{id, tcid, message_id}], status} where status is the
--    receipt status RIGHT NOW for this dispatch ('gone' if the order vanished): the "DB check after sending".
--    Mirrors t_order_card_sent (create_t_order_alerts.sql section 6).
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
-- 9. t_receipts_take(bot_key, order_number, order_type): claim this order's stale receipt copies for ONE refresh pass.
--    Returns jsonb {rows:[{id, tcid, message_id, tuid, dispatch_id, viewer_phone, authorised, taken_for}]}.
--    Fresh claims are taken_for 'edit'; a re-offered claim keeps its taken_for. FOR UPDATE SKIP LOCKED.
--    The outcome is recorded with t_order_card_mark() (create_t_order_alerts.sql section 9).
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
        public.t_order_card_destinations (p_bot_key, p_rest_ref) d
$$;

REVOKE ALL ON FUNCTION public.t_notice_targets (text, text, text, text) FROM PUBLIC, anon, authenticated;

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
-- 11. job_t_receipt_refresh(): the receipt sweep, every 5 seconds. Structure follows job_t_order_alerts()
--     (create_t_order_alerts.sql section 11) but has no schedule table: staleness is the whole signal.
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

-- pg_cron job 'job_t_receipt_refresh' (live schedule: 5 seconds, active). cron.schedule() updates the job in place when the name already exists.
SELECT
    cron.schedule ('job_t_receipt_refresh', '5 seconds', 'SELECT public.job_t_receipt_refresh()');

-- ---------------------------------------------------------------------------------------------
-- OPERATOR SQL (run by hand after the code is deployed; commented out on purpose)
-- ---------------------------------------------------------------------------------------------
-- SELECT cron.schedule('job_t_receipt_refresh', '5 seconds', $$SELECT public.job_t_receipt_refresh()$$);
-- To stop:  SELECT cron.unschedule('job_t_receipt_refresh');
-- Rollback of behaviour (no data loss): unschedule the job and redeploy the previous app build; the new columns are inert.
-- To inspect:  SELECT id, kind, subject_ref, dispatch_id, card_status, state FROM public.t_sent_messages
--               WHERE kind IN ('receipt', 'notice') ORDER BY id DESC LIMIT 20;
