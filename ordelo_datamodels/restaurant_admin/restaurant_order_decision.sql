-- =============================================================================================
-- ordelo_datamodels/restaurant_admin/restaurant_order_decision.sql
-- Accept / decline and pickup-time rules shared by WhatsApp and Telegram, plus the Telegram wrappers that authorise first.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     restaurant_admin_label(p_phone text) -> text
--                   Return the 'by X' label for an admin phone: the Telegram first name of its latest claimed invite, else '...' + last 4 digits.
--               fn     restaurant_order_decide(p_order_number text, p_order_type text, p_decision text, p_admin_phone text, p_channel text) -> jsonb
--                   Accept or decline an undecided order once (first decision wins); a decline also makes the order terminal.
--               fn     restaurant_order_set_pickup(p_order_number text, p_order_type text, p_pickup_time timestamp with time zone, p_admin_phone text, p_channel text) -> jsonb
--                   Set the pickup time of an accepted order that has none yet and make it dispatchable / confirmed.
--               fn     t_order_admin_phone(p_bot_key text, p_tuid bigint, p_rest_ref text) -> text
--                   Return the admin phone of a Telegram user for the order's restaurant (claimed invite whose phone is in admins), else NULL.
--               fn     t_order_decide(p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text, p_decision text) -> jsonb
--                   Telegram Accept / Decline: authorise the tapping person, then restaurant_order_decide().
--               fn     t_order_set_pickup(p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text, p_minutes integer) -> jsonb
--                   Telegram pickup button: authorise, then restaurant_order_set_pickup() with pickup = order time + p_minutes.
-- REQUIRES      telegram/t_invites.sql
--               restaurant_admin/admin_roster.sql
--               core/restaurant_master.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none when applied (functions only). Each decision UPDATE fires the restaurant trigger webhook.
-- HOW IT FITS   Today's WhatsApp callbacks and the Telegram buttons both call these functions, so the decision rule lives once,
--                 atomically, in the database (plans/telegram-rest-admin-scaffold-plan.md, D15-D19):
--                   restaurant_order_decide()      accept or decline; first decision wins; a decline sets status 'declined' in the
--                                                  same UPDATE so a declined delivery can never be dispatched (the R1-a bug)
--                   restaurant_order_set_pickup()  pickup time after an accept: delivery -> 'unassigned', takeaway -> 'pickup_confirmed'
--                   restaurant_admin_label()       the "by X" text shown on cards and messages
--                   t_order_admin_phone()          D14: is this Telegram person an admin of the order's restaurant?
--                   t_order_decide() / t_order_set_pickup()   Telegram: authorise (D14), then the shared function
--                 Tables used (defined elsewhere): delivery/delivery_summary.sql, takeaway/takeaway_summary.sql, telegram/t_invites.sql.
--                 trigger_restaurant_updates / trigger_takeaway_restaurant_updates fire on every restaurant_confirmation_status change
--                 and POST .../restaurant-confirmation-request, so payment capture/cancel, customer messages and the WhatsApp pickup
--                 prompts keep working through that webhook.
--                 Python: utils_common/order_management/restaurant_decision.py decide() / set_pickup();
--                         channels/telegram/rest_admin/order_cards/store.py CardStore.decide() / set_pickup() (Telegram taps).
-- LIFECYCLE     RESULT VOCABULARY (jsonb {result, ...})
--                 restaurant_order_decide:      ok | already_decided | not_found
--                 restaurant_order_set_pickup:  ok | already_set | not_accepted | not_found
--                 t_order_decide / t_order_set_pickup: the same, plus not_authorised (checked first after not_found)
--                 Bad arguments (unknown decision or order type) RAISE: a programming error.
-- CALLED BY     restaurant_admin_label:
--                 sql       restaurant_order_adjust_pickup() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--                 sql       restaurant_order_decide() (restaurant_admin/restaurant_order_decision.sql)
--                 sql       restaurant_order_ready() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--                 sql       restaurant_order_set_pickup() (restaurant_admin/restaurant_order_decision.sql)
--                 sql       t_order_card_snapshot() (telegram/t_order_alerts.sql)
--                 sql       t_receipt_snapshot() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--               restaurant_order_decide:
--                 sql       t_order_decide() (restaurant_admin/restaurant_order_decision.sql)
--                 python    utils_common/order_management/restaurant_decision.py: decide()
--                 python    watomation/routers/delivery_hooks.py: _handle_restaurant_decline()
--               restaurant_order_set_pickup:
--                 sql       t_order_set_pickup() (restaurant_admin/restaurant_order_decision.sql)
--                 python    utils_common/order_management/restaurant_decision.py: set_pickup()
--               t_order_admin_phone:
--                 sql       t_order_adjust_pickup() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--                 sql       t_order_decide() (restaurant_admin/restaurant_order_decision.sql)
--                 sql       t_order_ready() (restaurant_admin/restaurant_ready_adjust_notices.sql)
--                 sql       t_order_set_pickup() (restaurant_admin/restaurant_order_decision.sql)
--               t_order_decide:
--                 python    channels/telegram/rest_admin/order_cards/model.py: TapOutcome()
--                 python    channels/telegram/rest_admin/order_cards/store.py: CardStore.decide()
--                 python    utils_common/order_management/restaurant_decision.py (module-level SQL)
--               t_order_set_pickup:
--                 python    channels/telegram/rest_admin/order_cards/model.py: TapOutcome()
--                 python    channels/telegram/rest_admin/order_cards/store.py: CardStore.set_pickup()
--                 python    utils_common/order_management/restaurant_decision.py (module-level SQL)
-- PYTHON MODEL  none
-- SECURITY      Every function is revoked from PUBLIC/anon/authenticated: only the service key (client_ordelo_service) can call them.
--               The shared functions trust p_admin_phone; the t_ wrappers authorise first (claimed invite + phone in restaurant_master.admins).
-- TESTS         tests/sql/test_restaurant_decision_sql.py, tests/sql/test_order_taps_sql.py (loads this file into a throwaway Postgres)
--               tests/channels/telegram/test_order_card_store.py
--               tests/channels/telegram/test_order_taps.py
--               tests/sql/test_order_taps_sql.py
--               tests/sql/test_order_test_script_sql.py
--               tests/sql/test_restaurant_decision_sql.py
--               tests/utils_common/order_management/test_restaurant_decision.py
--               tests/watomation/test_on_callback_wa_handler.py
-- GOTCHAS       'restaurant_pickuptime_adjusted' (+10 / +20) is handled by restaurant_admin/restaurant_ready_adjust_notices.sql.
--               Auto-decline on timeout (R1) is out of scope: unanswered orders time out to a default pickup instead.
-- SEE ALSO      restaurant_admin/restaurant_ready_adjust_notices.sql
--               telegram/t_order_alerts.sql
--               telegram/t_invites.sql
--               docs/telegram-layer.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function restaurant_admin_label(p_phone text) -> text
--   Return the 'by X' label for an admin phone: the Telegram first name on its admin record (TRANSITION: else its latest claimed invite), else '...' + last 4 digits.
--   Data: reads restaurant_admin, t_invites (TRANSITION).
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 2. restaurant_admin_label(phone): the "by X" text (D19).
--    The Telegram first name of that phone's most recent claimed invite, else '...' + last 4 digits.
--    NULL for an empty phone. Reads t_invites (telegram/t_invites.sql).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_admin_label (p_phone text)
    RETURNS text
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        coalesce((
            SELECT
                ra.t_first_name
            FROM
                public.restaurant_admin ra
            WHERE
                ra.phone = public.admin_phone_digits (p_phone)
                AND ra.t_first_name IS NOT NULL),
            -- TRANSITION (P3 removes)
            (
                SELECT
                    i.telegram_first_name
                FROM
                    public.t_invites i
                WHERE
                    i.phone_number = p_phone
                    AND i.status = 'claimed'
                    AND i.telegram_first_name IS NOT NULL
                ORDER BY
                    i.claimed_at DESC
                LIMIT 1),
            CASE WHEN coalesce(p_phone, '') = '' THEN
                NULL
            ELSE
                '…' || RIGHT (p_phone, 4)
            END)
$$;

-- Server-only objects: nobody but the service key may call them.
REVOKE ALL ON FUNCTION public.restaurant_admin_label (text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function restaurant_order_decide(p_order_number text, p_order_type text, p_decision text, p_admin_phone text, p_channel text) -> jsonb
--   Accept or decline an undecided order once (first decision wins); a decline also makes the order terminal.
--   Data: writes delivery_summary, takeaway_summary; calls restaurant_admin_label().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 3. restaurant_order_decide(order_number, order_type, decision, admin_phone, channel)
--    p_order_type: 'delivery' | 'takeaway' (the food_order.action values)
--    p_decision:   'accept' | 'decline'
--    p_channel:    free text for logs/returns ('whatsapp' | 'telegram' | 'manual'); not stored.
--    One conditional UPDATE decides the winner: only a row still 'restaurant_unconfirmed' changes.
--    A decline also sets status = 'declined' in the same UPDATE (R1-a: never dispatchable).
--    Returns:
--      {result:'ok', decision, channel, decided_by (label), decided_by_phone}
--      {result:'already_decided', state, decided_by, decided_by_phone, decided_at, pickup_time}  (lost the race)
--      {result:'not_found'}
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_order_decide (p_order_number text, p_order_type text, p_decision text, p_admin_phone text, p_channel text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_rcs text := CASE p_decision
    WHEN 'accept' THEN
        'restaurant_accept'
    WHEN 'decline' THEN
        'restaurant_decline'
    END;
    v_cur record;
BEGIN
    IF v_rcs IS NULL OR p_order_type IS NULL OR p_order_type NOT IN ('delivery', 'takeaway') THEN
        RAISE EXCEPTION 'restaurant_order_decide: bad decision % or order type %', p_decision, p_order_type;
    END IF;

    IF p_order_type = 'delivery' THEN
        UPDATE
            public.delivery_summary
        SET
            restaurant_confirmation_status = v_rcs,
            status = CASE WHEN p_decision = 'decline' THEN
                'declined'
            ELSE
                status
            END,
            restaurant_admin = p_admin_phone,
            restaurant_update_dtts = now()
        WHERE
            order_number = p_order_number
            AND restaurant_confirmation_status = 'restaurant_unconfirmed';
    ELSE
        UPDATE
            public.takeaway_summary
        SET
            restaurant_confirmation_status = v_rcs,
            status = CASE WHEN p_decision = 'decline' THEN
                'declined'
            ELSE
                status
            END,
            restaurant_admin = p_admin_phone,
            restaurant_update_dtts = now()
        WHERE
            order_number = p_order_number
            AND restaurant_confirmation_status = 'restaurant_unconfirmed';
    END IF;

    IF FOUND THEN
        RETURN jsonb_build_object('result', 'ok', 'decision', p_decision, 'channel', p_channel, 'decided_by', public.restaurant_admin_label (p_admin_phone), 'decided_by_phone', p_admin_phone);
    END IF;
    -- Lost the race or already decided: report the authoritative state.
    IF p_order_type = 'delivery' THEN
        SELECT
            restaurant_confirmation_status AS rcs,
            restaurant_admin AS admin,
            restaurant_update_dtts AS decided_at,
            pickup_time INTO v_cur
        FROM
            public.delivery_summary
        WHERE
            order_number = p_order_number;
    ELSE
        SELECT
            restaurant_confirmation_status AS rcs,
            restaurant_admin AS admin,
            restaurant_update_dtts AS decided_at,
            pickup_time INTO v_cur
        FROM
            public.takeaway_summary
        WHERE
            order_number = p_order_number;
    END IF;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    RETURN jsonb_build_object('result', 'already_decided', 'state', v_cur.rcs, 'decided_by', public.restaurant_admin_label (v_cur.admin), 'decided_by_phone', v_cur.admin, 'decided_at', v_cur.decided_at, 'pickup_time', v_cur.pickup_time);
END
$$;

REVOKE ALL ON FUNCTION public.restaurant_order_decide (text, text, text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function restaurant_order_set_pickup(p_order_number text, p_order_type text, p_pickup_time timestamp with time zone, p_admin_phone text, p_channel text) -> jsonb
--   Set the pickup time of an accepted order that has none yet and make it dispatchable / confirmed.
--   Data: writes delivery_summary, takeaway_summary; calls restaurant_admin_label().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 4. restaurant_order_set_pickup(order_number, order_type, pickup_time, admin_phone, channel)
--    Same conditions and writes as the WhatsApp handler used (handle_pickup_time_selection): only an
--    ACCEPTED order with no pickup time yet changes; the delivery lifecycle moves to 'unassigned'
--    (dispatchable) and a takeaway to 'pickup_confirmed'.
--    Returns:
--      {result:'ok', pickup_time, decided_by, decided_by_phone}
--      {result:'already_set', state, pickup_time, decided_by, decided_by_phone}   pickup already chosen
--      {result:'not_accepted', state, decided_by, decided_by_phone}               declined, timed out, auto-accepted, or still unconfirmed
--      {result:'not_found'}
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_order_set_pickup (p_order_number text, p_order_type text, p_pickup_time timestamptz, p_admin_phone text, p_channel text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_cur record;
BEGIN
    IF p_order_type IS NULL OR p_order_type NOT IN ('delivery', 'takeaway') OR p_pickup_time IS NULL THEN
        RAISE EXCEPTION 'restaurant_order_set_pickup: bad order type % or missing pickup time', p_order_type;
    END IF;

    IF p_order_type = 'delivery' THEN
        UPDATE
            public.delivery_summary
        SET
            pickup_time = p_pickup_time,
            status = 'unassigned',
            restaurant_admin = p_admin_phone,
            restaurant_update_dtts = now()
        WHERE
            order_number = p_order_number
            AND restaurant_confirmation_status = 'restaurant_accept'
            AND pickup_time IS NULL;
    ELSE
        UPDATE
            public.takeaway_summary
        SET
            pickup_time = p_pickup_time,
            status = 'pickup_confirmed',
            restaurant_admin = p_admin_phone,
            restaurant_update_dtts = now()
        WHERE
            order_number = p_order_number
            AND restaurant_confirmation_status = 'restaurant_accept'
            AND pickup_time IS NULL;
    END IF;

    IF FOUND THEN
        RETURN jsonb_build_object('result', 'ok', 'pickup_time', p_pickup_time, 'decided_by', public.restaurant_admin_label (p_admin_phone), 'decided_by_phone', p_admin_phone);
    END IF;

    IF p_order_type = 'delivery' THEN
        SELECT
            restaurant_confirmation_status AS rcs,
            restaurant_admin AS admin,
            pickup_time INTO v_cur
        FROM
            public.delivery_summary
        WHERE
            order_number = p_order_number;
    ELSE
        SELECT
            restaurant_confirmation_status AS rcs,
            restaurant_admin AS admin,
            pickup_time INTO v_cur
        FROM
            public.takeaway_summary
        WHERE
            order_number = p_order_number;
    END IF;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    RETURN jsonb_build_object('result', CASE WHEN v_cur.pickup_time IS NOT NULL THEN
            'already_set'
        ELSE
            'not_accepted'
        END, 'state', v_cur.rcs, 'pickup_time', v_cur.pickup_time, 'decided_by', public.restaurant_admin_label (v_cur.admin), 'decided_by_phone', v_cur.admin);
END
$$;

REVOKE ALL ON FUNCTION public.restaurant_order_set_pickup (text, text, timestamptz, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_order_admin_phone(p_bot_key text, p_tuid bigint, p_rest_ref text) -> text
--   Return the admin phone of a Telegram user for the order's restaurant (linked admin record whose phone is in admins; TRANSITION: or a claimed invite), else NULL.
--   Data: calls admin_for_tuid(); reads admin_roster, restaurant_admin, t_invites (TRANSITION).
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 5. Telegram authorisation (D14, D25, D27). The actor is the Telegram USER (tuid = from_user.id), never the
--    chat: a button in a group chat is authorised exactly like one in a private chat.
--    t_order_admin_phone(bot_key, tuid, rest_ref): the admin phone this person is linked with for that
--    restaurant, or NULL. Allowed only when the person has a CLAIMED invite for the restaurant AND the invite's
--    phone is (digits compared) in restaurant_master.admins. Revoking the invite or removing the phone from
--    admins stops taps and alerts at once. Same rule as t_order_card_destinations() (telegram/t_order_alerts.sql).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_admin_phone (p_bot_key text, p_tuid bigint, p_rest_ref text)
    RETURNS text
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        coalesce(public.admin_for_tuid (p_tuid, p_rest_ref),
            -- TRANSITION (P3 removes): invite-linked admins whose phone has no admin record
            (
                SELECT
                    r.phone
                FROM
                    public.t_invites i
                    JOIN public.admin_roster r ON r.rest_ref = i.rest_ref
                        AND r.phone = public.admin_phone_digits (i.phone_number)
                WHERE
                    i.bot_key = p_bot_key
                    AND i.telegram_user_id = p_tuid
                    AND i.rest_ref = p_rest_ref
                    AND i.status = 'claimed'
                    AND NOT EXISTS (
                        SELECT
                            1
                        FROM
                            public.restaurant_admin ra
                        WHERE
                            ra.phone = r.phone)
                ORDER BY
                    i.claimed_at DESC NULLS LAST
                LIMIT 1))
$$;

REVOKE ALL ON FUNCTION public.t_order_admin_phone (text, bigint, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_order_decide(p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text, p_decision text) -> jsonb
--   Telegram Accept / Decline: authorise the tapping person, then restaurant_order_decide().
--   Data: reads delivery_summary, takeaway_summary; calls restaurant_order_decide(), t_order_admin_phone().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 6. t_order_decide(bot_key, tuid, order_number, order_type, decision): Telegram Accept / Decline.
--    Returns the restaurant_order_decide() jsonb, or {result:'not_found'} / {result:'not_authorised'}.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_decide (p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text, p_decision text)
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
        RAISE EXCEPTION 't_order_decide: bad order type %', p_order_type;
    END IF;
    IF v_rest_ref IS NULL THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    v_phone := public.t_order_admin_phone (p_bot_key, p_tuid, v_rest_ref);
    IF v_phone IS NULL THEN
        RETURN jsonb_build_object('result', 'not_authorised');
    END IF;
    RETURN public.restaurant_order_decide (p_order_number, p_order_type, p_decision, v_phone, 'telegram');
END
$$;

REVOKE ALL ON FUNCTION public.t_order_decide (text, bigint, text, text, text) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- function t_order_set_pickup(p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text, p_minutes integer) -> jsonb
--   Telegram pickup button: authorise, then restaurant_order_set_pickup() with pickup = order time + p_minutes.
--   Data: reads delivery_summary, takeaway_summary; calls restaurant_order_set_pickup(), t_order_admin_phone().
-- ---------------------------------------------------------------------------------------------
-- ---------------------------------------------------------------------------------------------
-- 7. t_order_set_pickup(bot_key, tuid, order_number, order_type, minutes): Telegram pickup-time button.
--    The pickup time is computed here as summary.dtts + minutes (parity with the WhatsApp buttons, which offer
--    the order time + 5 / 15 / 25 minutes), so the button carries minutes, not a timestamp. minutes must be
--    1..120 (anything else is a programming error and RAISES).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_set_pickup (p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text, p_minutes int)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_rest_ref text;
    v_dtts timestamptz;
    v_phone text;
BEGIN
    IF p_minutes IS NULL OR p_minutes < 1 OR p_minutes > 120 THEN
        RAISE EXCEPTION 't_order_set_pickup: bad minutes %', p_minutes;
    END IF;
    IF p_order_type = 'delivery' THEN
        SELECT
            rest_ref,
            dtts INTO v_rest_ref,
            v_dtts
        FROM
            public.delivery_summary
        WHERE
            order_number = p_order_number;
    ELSIF p_order_type = 'takeaway' THEN
        SELECT
            rest_ref,
            dtts INTO v_rest_ref,
            v_dtts
        FROM
            public.takeaway_summary
        WHERE
            order_number = p_order_number;
    ELSE
        RAISE EXCEPTION 't_order_set_pickup: bad order type %', p_order_type;
    END IF;
    IF v_rest_ref IS NULL THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    v_phone := public.t_order_admin_phone (p_bot_key, p_tuid, v_rest_ref);
    IF v_phone IS NULL THEN
        RETURN jsonb_build_object('result', 'not_authorised');
    END IF;
    RETURN public.restaurant_order_set_pickup (p_order_number, p_order_type, v_dtts + make_interval(mins => p_minutes), v_phone, 'telegram');
END
$$;

REVOKE ALL ON FUNCTION public.t_order_set_pickup (text, bigint, text, text, int) FROM PUBLIC, anon, authenticated;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.restaurant_admin_label (p_phone text) IS 'Return the ''by X'' label for an admin phone: the Telegram first name of its latest claimed invite, else ''...'' + last 4 digits.';

COMMENT ON FUNCTION public.restaurant_order_decide (p_order_number text, p_order_type text, p_decision text, p_admin_phone text, p_channel text) IS 'Accept or decline an undecided order once (first decision wins); a decline also makes the order terminal.';

COMMENT ON FUNCTION public.restaurant_order_set_pickup (p_order_number text, p_order_type text, p_pickup_time timestamp with time zone, p_admin_phone text, p_channel text) IS 'Set the pickup time of an accepted order that has none yet and make it dispatchable / confirmed.';

COMMENT ON FUNCTION public.t_order_admin_phone (p_bot_key text, p_tuid bigint, p_rest_ref text) IS 'Return the admin phone of a Telegram user for the order''s restaurant (linked admin record whose phone is in admins; TRANSITION: or a claimed invite), else NULL.';

COMMENT ON FUNCTION public.t_order_decide (p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text, p_decision text) IS 'Telegram Accept / Decline: authorise the tapping person, then restaurant_order_decide().';

COMMENT ON FUNCTION public.t_order_set_pickup (p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text, p_minutes integer) IS 'Telegram pickup button: authorise, then restaurant_order_set_pickup() with pickup = order time + p_minutes.';
