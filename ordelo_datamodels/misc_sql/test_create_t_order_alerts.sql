-- =============================================================================================
-- TEST HARNESS (not a migration): re-runnable fake STRK order for testing the Telegram order card
-- =============================================================================================
-- Run the WHOLE file in the Supabase SQL editor every time you want a fresh test. Each run:
--   1. wipes every earlier test order and its Telegram bookkeeping, then
--   2. inserts a brand-new delivery_summary row in 'restaurant_unconfirmed'.
-- Within ~5 s the job_t_order_alerts() sweep seeds the reminders and the card arrives in the Telegram chat of every
-- linked STRK admin, then again at +15 / +30 / +45 s ("reminder n of 4"). Tap Accept / Decline / a pickup time.
--
-- WHAT IT TOUCHES (and only for orders whose number starts with STRK-TEST-)
--   delete+insert  delivery_summary        the fake order itself (every run starts clean: no pickup, no admin)
--   delete         t_order_alerts          the reminder schedule rows of earlier test orders
--   delete         t_sent_messages         the ledger of earlier cards
--   delete         debug_log               trigger debug rows for the test order (only if that table exists)
-- It does NOT touch t_inbox (keyed by Telegram update id, not by order), restaurant_master, t_invites, any real order,
-- or any other restaurant. Telegram messages from earlier runs stay in the chat but are dead: tapping one answers
-- "This order is no longer available." (the order number differs on every run).
--
-- WHY NO food_order ROW
--   The existing trigger on delivery_summary POSTs the restaurant-confirmation webhook (WhatsApp prompts, payment
--   capture/cancel, customer messages) only when a food_order row exists for the order number; without one it logs a
--   warning and stops. The test order deliberately has none, so ONLY the Telegram flow is exercised: no payment call,
--   no customer message. Consequences: the card shows no total or items, and an Accept does not capture a payment.
--   There is no delivery_detail row either, so the order can never be dispatched to riders.
--
-- PREREQUISITES
--   * create_t_inbox.sql, restaurant_order_decision.sql and create_t_order_alerts.sql applied, job_t_order_alerts() scheduled.
--   * A CLAIMED t_invites row for rest_ref 'STRK' whose phone is 447448440754 (it is in restaurant_master.admins for STRK).
--     The last query of this file shows whether one exists (destinations > 0). If not, create and claim one first (see the
--     Telegram Invites section of the database-operations skill).
--   * The auto-timeout job (RESTAURANT_CONFIRMATION_TIMEOUT, default 5 min) will time the order out if nobody answers; that
--     is a handy way to see the "Auto-accepted" card, otherwise tap within 5 minutes.
-- =============================================================================================
INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id, telegram_first_name)
SELECT 'STRK', '447448440754', 'claimed', now(), telegram_user_id, telegram_chat_id, telegram_first_name
  FROM public.t_invites WHERE status = 'claimed' AND telegram_user_id IS NOT NULL
 ORDER BY claimed_at DESC LIMIT 1;


DO $$
BEGIN
    IF to_regclass('public.debug_log') IS NOT NULL THEN
        EXECUTE $q$DELETE FROM public.debug_log WHERE order_number LIKE 'STRK-TEST-%'$q$;
    END IF;
END $$;
-- 1. Clean slate: bookkeeping first, then the order.
DELETE FROM public.t_order_alerts  WHERE order_number LIKE 'STRK-TEST-%';
DELETE FROM public.t_sent_messages WHERE subject_type = 'order' AND subject_ref LIKE 'STRK-TEST-%';
DELETE FROM public.delivery_summary WHERE order_number LIKE 'STRK-TEST-%';

-- 2. The fake order. New number every run (STRK-TEST-<HHMMSS, UTC>); dtts = now() restarts the reminder clock.
--    rest_id is a placeholder on purpose: STRK has no restaurant_master.rest_id and nothing should message it.
INSERT INTO public.delivery_summary (
    order_number, rest_id, rest_name, rest_lon, rest_lat, rest_address, town,
    customer_id, customer_name, customer_lon, customer_lat, customer_address,
    restaurant_confirmation_status, status, rest_confirmation_code, cust_confirmation_code,
    dtts
) VALUES (
    'STRK-TEST-' || to_char(now() AT TIME ZONE 'UTC', 'HH24MISS'),
    'STRK-TEST', 'Strikers Sports Bar', 0.100950805301294, 51.3766272547284,
    '40b The Walnuts High Street Orpington BR6 0TW', 'dummy',
    '447448440754', 'Test Customer', 0.1008, 51.3764, '1 Test Street Orpington BR6 0TW',
    'restaurant_unconfirmed', 'restaurant_unconfirmed', 70, 47,
    now()
);

-- 3. What you should see now (the editor shows this last result): the new order, and how many Telegram chats will get its card.
SELECT s.order_number,
       s.restaurant_confirmation_status,
       s.status,
       s.dtts,
       s.pickup_date,
       s.pickup_time,
       (SELECT count(*) FROM public.t_order_card_destinations('rest_admin', s.rest_ref)) AS telegram_destinations
  FROM public.delivery_summary s
 WHERE s.order_number LIKE 'STRK-TEST-%';

-- ---------------------------------------------------------------------------------------------
-- WATCH IT (run separately, any time)
-- ---------------------------------------------------------------------------------------------
-- The order after your taps (decision, who, pickup):
--   SELECT order_number, restaurant_confirmation_status, status, restaurant_admin, pickup_time
--     FROM public.delivery_summary WHERE order_number LIKE 'STRK-TEST-%';
-- The reminder schedule (pending -> sent / superseded / cancelled):
--   SELECT offset_secs, n, of_n, status, due_at FROM public.t_order_alerts WHERE order_number LIKE 'STRK-TEST-%' ORDER BY offset_secs;
-- The Telegram copies (live -> taken -> closed; card_status = what each copy shows):
--   SELECT id, tcid, message_id, card_status, state, taken_for, close_reason FROM public.t_sent_messages WHERE subject_ref LIKE 'STRK-TEST-%' ORDER BY id;
-- Your taps as the bot saw them (newest first; status done / failed + error):
--   SELECT update_id, kind, tuid, status, error, received_at FROM public.t_inbox ORDER BY received_at DESC LIMIT 10;
-- Who is linked (should list your chat):
--   SELECT * FROM public.t_order_card_destinations('rest_admin', 'STRK');

-- ---------------------------------------------------------------------------------------------
-- NO CARD ARRIVES? telegram_destinations above is 0. Cards go ONLY to chats linked to this order's restaurant
-- (t_invites row with rest_ref = 'STRK', status 'claimed', phone listed in restaurant_master.admins for STRK).
-- A chat you opened under another restaurant's invite (say ELAS) does not count. See what you have linked:
--   SELECT rest_ref, phone_number, status, telegram_user_id, telegram_chat_id, telegram_first_name, claimed_at
--     FROM public.t_invites WHERE status = 'claimed' ORDER BY claimed_at DESC;
-- Fix A (the real flow): INSERT INTO public.t_invites (rest_ref, phone_number) VALUES ('STRK', '447448440754') RETURNING invite_code;
--        then open  https://t.me/<your_bot>?start=<invite_code>  and tap the confirm button.
-- Fix B (test-only shortcut, reuses the chat you already have, no bot step): copy your Telegram ids onto a STRK invite.
--   INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id, telegram_first_name)
--   SELECT 'STRK', '447448440754', 'claimed', now(), telegram_user_id, telegram_chat_id, telegram_first_name
--     FROM public.t_invites WHERE status = 'claimed' AND telegram_user_id IS NOT NULL
--    ORDER BY claimed_at DESC LIMIT 1;
-- Then run the top of this file again (a fresh order) - the existing order only seeds reminders once a destination exists.
