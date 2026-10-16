-- =============================================================================================
-- Feature SQL: shared restaurant decision functions (accept / decline / pickup time) + R1-a
-- =============================================================================================
-- See also (paths under ordelo_datamodels/): sibling files: restaurant_admin/restaurant_ready_adjust_notices.sql (Ready / adjust / receipts / notices, run after this one), telegram/create_t_order_alerts.sql (Telegram order cards).
-- Run in the Supabase SQL editor (operator step; the implementing agent never runs it).
-- Repeatable: the constraint change is DROP IF EXISTS + ADD, every function is CREATE OR REPLACE.
-- Run it BEFORE deploying the code that calls it (utils_common/order_management/restaurant_decision.py).
-- It changes a LIVE CHECK constraint on delivery_summary (adds 'declined'): a brief table lock, no data change.
-- Phase 5 appends two more functions to this same file (t_order_decide, t_order_set_pickup) and it is re-run.
--
-- WHAT THIS ADDS
--   Constraint  delivery_summary_status_check   now also allows 'declined'   (R1-a, see below)
--   Functions   restaurant_admin_label()        "by X" label for an admin phone (D19)
--               restaurant_order_decide()       accept or decline an order; first decision wins (D18)
--               restaurant_order_set_pickup()   choose the pickup time after an accept
--               t_order_admin_phone()           D14: is this Telegram person an admin of the order's restaurant?
--               t_order_decide()                Telegram Accept / Decline: authorise (D14), then restaurant_order_decide()
--               t_order_set_pickup()            Telegram pickup button: authorise (D14), pickup = order time + N minutes
--
-- WHY (plans/telegram-rest-admin-scaffold-plan.md, decisions D15-D19)
--   Today the WhatsApp handler does a read-modify-write through the REST client and the delivery decline
--   handler then sets status = 'unassigned', which makes a DECLINED delivery order dispatchable (the R1-a bug).
--   The Telegram buttons (phase 5) need the same rule. So the rule lives here, once, atomically:
--   a decline sets status = 'declined' in the SAME UPDATE as the decision, so the order can never be
--   dispatched (dispatch only selects status = 'unassigned').
--
-- HOW THE PIECES FIT TOGETHER
--   Tables used (defined elsewhere): ordelo_datamodels/summary.sql (delivery_summary),
--     ordelo_datamodels/takeaway_summary.sql (takeaway_summary), create_t_invites.sql (t_invites, for the label).
--   Triggers (unchanged): trigger_restaurant_updates / trigger_takeaway_restaurant_updates fire on every
--     restaurant_confirmation_status change and POST /delivery-hooks|/takeaway-hooks .../restaurant-confirmation-request.
--     Payment capture/cancel, customer messages and the WhatsApp pickup prompts keep working through that webhook.
--   Callers (keep in sync with the module docstring of utils_common/order_management/restaurant_decision.py):
--       restaurant_decision.decide()      -> restaurant_order_decide()
--       restaurant_decision.set_pickup()  -> restaurant_order_set_pickup()
--       (restaurant_admin_label() is called inside restaurant_order_decide / set_pickup and, from phase 5,
--        by channels/telegram/rest_admin/order_cards/store.py through the order snapshot)
--       channels/telegram/rest_admin/order_cards/store.py (Telegram taps, OrderCards.tap):
--         CardStore.decide()      -> t_order_decide(p_bot_key, p_tuid, p_order_number, p_order_type, p_decision)
--         CardStore.set_pickup()  -> t_order_set_pickup(p_bot_key, p_tuid, p_order_number, p_order_type, p_minutes)
--         (both call the two shared functions above in one transaction, so Telegram and WhatsApp follow one rule)
--
-- RESULT VOCABULARY (jsonb {result, ...})
--   restaurant_order_decide:      ok | already_decided | not_found
--   restaurant_order_set_pickup:  ok | already_set | not_accepted | not_found
--   t_order_decide / t_order_set_pickup: the same, plus not_authorised (checked FIRST after not_found)
--   Bad arguments (unknown decision or order type) RAISE an exception: that is a programming error.
--
-- SECURITY MODEL
--   All three functions are revoked from PUBLIC/anon/authenticated: only the service key can call them
--   (client_ordelo_service). They trust p_admin_phone: authorising WHO may decide is the caller's job
--   (WhatsApp: the sender is an admin by construction; Telegram: t_order_decide checks t_invites + admins).
--
-- NOT YET DONE
--   * 'restaurant_pickuptime_adjusted' (admin adjusts an already-set pickup) still goes through
--     watomation/on_callback_wa_handler.py admin_adjust_pickup_time, not through these functions.
--   * Auto-decline on timeout (R1) is out of scope.
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- 1. R1-a: delivery orders can be terminally declined. (takeaway_summary already allows 'declined'.)
--    The constraint name was verified on the live database on 15 Oct 2026.
-- ---------------------------------------------------------------------------------------------
ALTER TABLE public.delivery_summary DROP CONSTRAINT IF EXISTS delivery_summary_status_check;
ALTER TABLE public.delivery_summary ADD CONSTRAINT delivery_summary_status_check
    CHECK (status IN ('restaurant_unconfirmed', 'unassigned', 'timedout', 'assigned', 'completed', 'declined'));

-- ---------------------------------------------------------------------------------------------
-- 2. restaurant_admin_label(phone): the "by X" text (D19).
--    The Telegram first name of that phone's most recent claimed invite, else '...' + last 4 digits.
--    NULL for an empty phone. Reads t_invites (create_t_invites.sql).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.restaurant_admin_label(p_phone text)
RETURNS text LANGUAGE sql STABLE SET search_path = public AS $$
    SELECT COALESCE(
        (SELECT i.telegram_first_name
           FROM public.t_invites i
          WHERE i.phone_number = p_phone
            AND i.status = 'claimed'
            AND i.telegram_first_name IS NOT NULL
          ORDER BY i.claimed_at DESC
          LIMIT 1),
        CASE WHEN coalesce(p_phone, '') = '' THEN NULL ELSE '…' || right(p_phone, 4) END)
$$;

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
CREATE OR REPLACE FUNCTION public.restaurant_order_decide(
    p_order_number text, p_order_type text, p_decision text, p_admin_phone text, p_channel text)
RETURNS jsonb LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    v_rcs text := CASE p_decision WHEN 'accept' THEN 'restaurant_accept' WHEN 'decline' THEN 'restaurant_decline' END;
    v_cur record;
BEGIN
    IF v_rcs IS NULL OR p_order_type IS NULL OR p_order_type NOT IN ('delivery', 'takeaway') THEN
        RAISE EXCEPTION 'restaurant_order_decide: bad decision % or order type %', p_decision, p_order_type;
    END IF;

    IF p_order_type = 'delivery' THEN
        UPDATE public.delivery_summary
           SET restaurant_confirmation_status = v_rcs,
               status = CASE WHEN p_decision = 'decline' THEN 'declined' ELSE status END,
               restaurant_admin = p_admin_phone,
               restaurant_update_dtts = now()
         WHERE order_number = p_order_number
           AND restaurant_confirmation_status = 'restaurant_unconfirmed';
    ELSE
        UPDATE public.takeaway_summary
           SET restaurant_confirmation_status = v_rcs,
               status = CASE WHEN p_decision = 'decline' THEN 'declined' ELSE status END,
               restaurant_admin = p_admin_phone,
               restaurant_update_dtts = now()
         WHERE order_number = p_order_number
           AND restaurant_confirmation_status = 'restaurant_unconfirmed';
    END IF;

    IF FOUND THEN
        RETURN jsonb_build_object(
            'result', 'ok', 'decision', p_decision, 'channel', p_channel,
            'decided_by', public.restaurant_admin_label(p_admin_phone),
            'decided_by_phone', p_admin_phone);
    END IF;

    -- Lost the race or already decided: report the authoritative state.
    IF p_order_type = 'delivery' THEN
        SELECT restaurant_confirmation_status AS rcs, restaurant_admin AS admin,
               restaurant_update_dtts AS decided_at, pickup_time
          INTO v_cur FROM public.delivery_summary WHERE order_number = p_order_number;
    ELSE
        SELECT restaurant_confirmation_status AS rcs, restaurant_admin AS admin,
               restaurant_update_dtts AS decided_at, pickup_time
          INTO v_cur FROM public.takeaway_summary WHERE order_number = p_order_number;
    END IF;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    RETURN jsonb_build_object(
        'result', 'already_decided', 'state', v_cur.rcs,
        'decided_by', public.restaurant_admin_label(v_cur.admin),
        'decided_by_phone', v_cur.admin,
        'decided_at', v_cur.decided_at,
        'pickup_time', v_cur.pickup_time);
END $$;

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
CREATE OR REPLACE FUNCTION public.restaurant_order_set_pickup(
    p_order_number text, p_order_type text, p_pickup_time timestamptz, p_admin_phone text, p_channel text)
RETURNS jsonb LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    v_cur record;
BEGIN
    IF p_order_type IS NULL OR p_order_type NOT IN ('delivery', 'takeaway') OR p_pickup_time IS NULL THEN
        RAISE EXCEPTION 'restaurant_order_set_pickup: bad order type % or missing pickup time', p_order_type;
    END IF;

    IF p_order_type = 'delivery' THEN
        UPDATE public.delivery_summary
           SET pickup_time = p_pickup_time,
               status = 'unassigned',
               restaurant_admin = p_admin_phone,
               restaurant_update_dtts = now()
         WHERE order_number = p_order_number
           AND restaurant_confirmation_status = 'restaurant_accept'
           AND pickup_time IS NULL;
    ELSE
        UPDATE public.takeaway_summary
           SET pickup_time = p_pickup_time,
               status = 'pickup_confirmed',
               restaurant_admin = p_admin_phone,
               restaurant_update_dtts = now()
         WHERE order_number = p_order_number
           AND restaurant_confirmation_status = 'restaurant_accept'
           AND pickup_time IS NULL;
    END IF;

    IF FOUND THEN
        RETURN jsonb_build_object(
            'result', 'ok', 'pickup_time', p_pickup_time,
            'decided_by', public.restaurant_admin_label(p_admin_phone),
            'decided_by_phone', p_admin_phone);
    END IF;

    IF p_order_type = 'delivery' THEN
        SELECT restaurant_confirmation_status AS rcs, restaurant_admin AS admin, pickup_time
          INTO v_cur FROM public.delivery_summary WHERE order_number = p_order_number;
    ELSE
        SELECT restaurant_confirmation_status AS rcs, restaurant_admin AS admin, pickup_time
          INTO v_cur FROM public.takeaway_summary WHERE order_number = p_order_number;
    END IF;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    RETURN jsonb_build_object(
        'result', CASE WHEN v_cur.pickup_time IS NOT NULL THEN 'already_set' ELSE 'not_accepted' END,
        'state', v_cur.rcs,
        'pickup_time', v_cur.pickup_time,
        'decided_by', public.restaurant_admin_label(v_cur.admin),
        'decided_by_phone', v_cur.admin);
END $$;

-- ---------------------------------------------------------------------------------------------
-- 5. Telegram authorisation (D14, D25, D27). The actor is the Telegram USER (tuid = from_user.id), never the
--    chat: a button in a group chat is authorised exactly like one in a private chat.
--    t_order_admin_phone(bot_key, tuid, rest_ref): the admin phone this person is linked with for that
--    restaurant, or NULL. Allowed only when the person has a CLAIMED invite for the restaurant AND the invite's
--    phone is (digits compared) in restaurant_master.admins. Revoking the invite or removing the phone from
--    admins stops taps and alerts at once. Same rule as t_order_card_destinations() (create_t_order_alerts.sql).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_admin_phone(p_bot_key text, p_tuid bigint, p_rest_ref text)
RETURNS text LANGUAGE sql STABLE SET search_path = public AS $$
    SELECT i.phone_number
      FROM public.t_invites i
      JOIN public.restaurant_master rm ON rm.rest_ref = i.rest_ref
     WHERE i.bot_key = p_bot_key
       AND i.telegram_user_id = p_tuid
       AND i.rest_ref = p_rest_ref
       AND i.status = 'claimed'
       AND i.phone_number IN (SELECT regexp_replace(a, '\D', '', 'g') FROM unnest(rm.admins) AS a)
     ORDER BY i.claimed_at DESC NULLS LAST
     LIMIT 1
$$;

-- ---------------------------------------------------------------------------------------------
-- 6. t_order_decide(bot_key, tuid, order_number, order_type, decision): Telegram Accept / Decline.
--    Returns the restaurant_order_decide() jsonb, or {result:'not_found'} / {result:'not_authorised'}.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_decide(
    p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text, p_decision text)
RETURNS jsonb LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    v_rest_ref text;
    v_phone text;
BEGIN
    IF p_order_type = 'delivery' THEN
        SELECT rest_ref INTO v_rest_ref FROM public.delivery_summary WHERE order_number = p_order_number;
    ELSIF p_order_type = 'takeaway' THEN
        SELECT rest_ref INTO v_rest_ref FROM public.takeaway_summary WHERE order_number = p_order_number;
    ELSE
        RAISE EXCEPTION 't_order_decide: bad order type %', p_order_type;
    END IF;
    IF v_rest_ref IS NULL THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    v_phone := public.t_order_admin_phone(p_bot_key, p_tuid, v_rest_ref);
    IF v_phone IS NULL THEN
        RETURN jsonb_build_object('result', 'not_authorised');
    END IF;
    RETURN public.restaurant_order_decide(p_order_number, p_order_type, p_decision, v_phone, 'telegram');
END $$;

-- ---------------------------------------------------------------------------------------------
-- 7. t_order_set_pickup(bot_key, tuid, order_number, order_type, minutes): Telegram pickup-time button.
--    The pickup time is computed here as summary.dtts + minutes (parity with the WhatsApp buttons, which offer
--    the order time + 5 / 15 / 25 minutes), so the button carries minutes, not a timestamp. minutes must be
--    1..120 (anything else is a programming error and RAISES).
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.t_order_set_pickup(
    p_bot_key text, p_tuid bigint, p_order_number text, p_order_type text, p_minutes int)
RETURNS jsonb LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    v_rest_ref text;
    v_dtts timestamptz;
    v_phone text;
BEGIN
    IF p_minutes IS NULL OR p_minutes < 1 OR p_minutes > 120 THEN
        RAISE EXCEPTION 't_order_set_pickup: bad minutes %', p_minutes;
    END IF;
    IF p_order_type = 'delivery' THEN
        SELECT rest_ref, dtts INTO v_rest_ref, v_dtts FROM public.delivery_summary WHERE order_number = p_order_number;
    ELSIF p_order_type = 'takeaway' THEN
        SELECT rest_ref, dtts INTO v_rest_ref, v_dtts FROM public.takeaway_summary WHERE order_number = p_order_number;
    ELSE
        RAISE EXCEPTION 't_order_set_pickup: bad order type %', p_order_type;
    END IF;
    IF v_rest_ref IS NULL THEN
        RETURN jsonb_build_object('result', 'not_found');
    END IF;
    v_phone := public.t_order_admin_phone(p_bot_key, p_tuid, v_rest_ref);
    IF v_phone IS NULL THEN
        RETURN jsonb_build_object('result', 'not_authorised');
    END IF;
    RETURN public.restaurant_order_set_pickup(
        p_order_number, p_order_type, v_dtts + make_interval(mins => p_minutes), v_phone, 'telegram');
END $$;

-- Server-only objects: nobody but the service key may call them.
REVOKE ALL ON FUNCTION public.restaurant_admin_label(text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.restaurant_order_decide(text, text, text, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.restaurant_order_set_pickup(text, text, timestamptz, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.t_order_admin_phone(text, bigint, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.t_order_decide(text, bigint, text, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.t_order_set_pickup(text, bigint, text, text, int) FROM PUBLIC, anon, authenticated;
