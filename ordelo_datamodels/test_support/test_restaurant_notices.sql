-- =============================================================================================
-- TEST HARNESS (not a migration): fake STRK orders to try the kitchen receipt, Ready / +10 / +20 and the restaurant
-- notices on WhatsApp AND Telegram, end to end, without a real customer, restaurant or rider.
-- =============================================================================================
-- Run it ONE STAGE AT A TIME in the Supabase SQL editor (each block starts with "-- ===== STAGE n ... =====").
-- Stages that say "you tap" only show state: the action is yours (WhatsApp, Telegram or the rider chat).
-- Every stage can be repeated. STAGE 0 wipes every earlier STRK test order first, so start there.
--
-- WHAT IT TOUCHES (and only rows whose order number starts with STRK-TEST-)
--   delete        rider_pickup_alert, order_notification_subscription, notification_outbox, order_customer_event,
--                 t_order_alerts, t_sent_messages (cards, receipts, notices of those orders), delivery_inflight,
--                 delivery_dispatch, delivery_detail, delivery_summary, takeaway_summary, order_item, food_order,
--                 debug_log (only if those tables exist)
--   insert        food_order + order_item (through create_food_order_with_items, the function real orders use),
--                 delivery_summary, takeaway_summary, and (STAGE 2b, only after you accepted) delivery_detail
--   insert once   a claimed STRK invite for 447448440754, copied from the chat you already linked, only if none exists
--   update        thread: STAGE 0 closes (never deletes) the rider threads of STRK-TEST dispatches (after rider_telegram_r2_r4.sql)
-- It only READS restaurant_master (the STRK row: the order webhooks look the restaurant up by its rest_id) and rider_master;
-- it does NOT change restaurant_master, riders, ordelo_config, any other restaurant, any other order.
-- Messages already in your chats stay there, but their buttons answer "This order is no longer available."
--
-- SIDE-EFFECT SAFETY (checked offline: tests/regressions/test_p7d_test_order_safety.py and
--                     tests/sql/test_restaurant_notices_script_sql.py)
--   * EVERY fake order has an exact `TEST3100` item (price 1.00). That makes create_food_order_with_items save
--     payment_mode = 'test', so FoodOrder.payment_uri points at ms_settings.stripe_url_test (the Wren TEST payment
--     service), never the live one. A delivery order with this item is offered ONLY to riders in
--     ordelo_config.overwatch_list; a takeaway creates no rider dispatch. (docs/test-orders.md)
--   * The payment calls that remain are made to the TEST service for a thread that does not exist there:
--       delivery capture (at rider accept) and cancel   -> an HTTP 4xx, caught and logged (httpx.HTTPError), returns None
--       takeaway 'test_no_payment' (STAGE 8)            -> returns before any HTTP call; ONE overwatch message
--                                                          "capture reconciliation" about the test order is expected
--       takeaway 'pay_at_rest' (STAGE 8b)               -> ONE print-only job request to the TEST service (a receipt
--                                                          job, not a Stripe payment). Run STAGE 8b only if you accept that.
--     generate_product_order_summary (used by the capture payload) only reads order_item; it calls nothing outside.
--   * Customer = 447448440754 and origin_channel = 'whatsapp', so customer messages reach your WhatsApp only.
--   * town = 'dummy' on every order, so only riders you put in town 'dummy' ever get an offer.
--
-- PREREQUISITES (the check query below shows each)
--   * create_t_inbox, create_t_invites, restaurant_order_decision, create_t_order_alerts and restaurant_ready_adjust_notices
--     applied; job_t_order_alerts, job_t_receipt_refresh, job_rider_pickup_alerts and the dispatch jobs scheduled.
--   * The restaurant_master row for rest_ref 'STRK' (your phone in admins) MUST have a rest_id: every fake order uses THAT
--     rest_id, because the order webhooks read the restaurant by rest_id (a made-up one fails with "restaurant_master ...
--     Input should be a valid dictionary" and no WhatsApp prompt / auto-accept happens). STRK has none today, so run ONCE
--     (an owner step, it changes one restaurant_master row; nothing else uses that id):
--       UPDATE public.restaurant_master SET rest_id = 'STRK01' WHERE rest_ref = 'STRK' AND rest_id IS NULL;
--   * A CLAIMED t_invites row for rest_ref 'STRK' whose phone is 447448440754 (STAGE 0 copies yours if missing).
--   * At least one rider_master row with town = 'dummy', status = 'active' (the dispatch gate since 2026-10-22),
--     is_in_shift = true and a vehicle_type your dispatch offers, whose
--     rider_id is ALSO listed in ordelo_config 'overwatch_list' (TEST3100 orders go to overwatch riders only).
--     For the race test add a second such rider.
--   * ORDELO_APP_URL in ordelo_config pointing at the instance under test (tunnel for local runs, docs/local-testing-runbook.md).
--
-- NOTHING ARRIVES? Check in this order: the PREREQUISITES query; STAGE 1's last query (telegram_destinations > 0);
--   the cron jobs (SELECT jobname, schedule, active FROM cron.job ORDER BY 1); the app logs for /delivery-hooks and
--   /telegram/rest-admin/order-alerts; t_receipts_stale('rest_admin') (copies waiting for the 5-second job).
-- =============================================================================================

-- ===== PREREQUISITES CHECK (read only) =====
SELECT (SELECT count(*) FROM public.t_order_card_destinations('rest_admin', 'STRK'))                 AS telegram_destinations,    -- >= 1
       (SELECT count(*) FROM pg_proc WHERE proname IN ('restaurant_order_ready', 't_receipt_snapshot', 'job_t_receipt_refresh',
                                                       'create_food_order_with_items'))              AS functions_present,        -- 4
       (SELECT rest_id FROM public.restaurant_master WHERE rest_ref = 'STRK')                        AS strk_rest_id,             -- NOT NULL
       (SELECT count(*) FROM public.rider_master WHERE town = 'dummy' AND is_in_shift AND status = 'active') AS dummy_riders_in_shift, -- >= 1
       (SELECT config_value FROM public.ordelo_config WHERE config_key = 'overwatch_list')           AS overwatch_list,           -- has your rider
       (SELECT config_value FROM public.ordelo_config WHERE config_key = 'ORDELO_APP_URL')           AS app_url;
-- Cron (Supabase only):  SELECT jobname, schedule, active FROM cron.job WHERE jobname IN
--   ('job_t_order_alerts', 'job_t_receipt_refresh', 'job_rider_pickup_alerts') ORDER BY 1;     -- 3 rows, active
-- To schedule the receipt sweep (operator step, once):
--   SELECT cron.schedule('job_t_receipt_refresh', '5 seconds', $$SELECT public.job_t_receipt_refresh()$$);


-- ===== STAGE 0: RESET (wipes earlier STRK-TEST orders; links your chat to STRK if needed) =====
-- Rider threads of the fake jobs are CLOSED first (never deleted), so the rider is not left in a finished fake job
-- (rider_threads.sql; skipped until migrations/rider_telegram_r2_r4.sql added delivery_dispatch.thread_id).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'delivery_dispatch' AND column_name = 'thread_id') THEN
        EXECUTE $q$UPDATE public.thread t SET is_active = FALSE FROM public.delivery_dispatch d
                    WHERE d.thread_id = t.thread_id AND d.order_number LIKE 'STRK-TEST-%' AND t.is_active IS TRUE$q$;
    END IF;
END $$;

DO $$
DECLARE s record;
BEGIN
    FOR s IN SELECT * FROM (VALUES
        ('public.rider_pickup_alert',            $q$DELETE FROM public.rider_pickup_alert WHERE order_number LIKE 'STRK-TEST-%'$q$),
        ('public.notification_outbox',           $q$DELETE FROM public.notification_outbox WHERE event_id IN
                                                     (SELECT id FROM public.order_customer_event WHERE order_number LIKE 'STRK-TEST-%')$q$),
        ('public.order_customer_event',          $q$DELETE FROM public.order_customer_event WHERE order_number LIKE 'STRK-TEST-%'$q$),
        ('public.order_notification_subscription', $q$DELETE FROM public.order_notification_subscription WHERE order_number LIKE 'STRK-TEST-%'$q$),
        ('public.t_order_alerts',                $q$DELETE FROM public.t_order_alerts WHERE order_number LIKE 'STRK-TEST-%'$q$),
        ('public.t_sent_messages',               $q$DELETE FROM public.t_sent_messages
                                                     WHERE (subject_type = 'order' AND subject_ref LIKE 'STRK-TEST-%')
                                                        OR (subject_type = 'rest' AND subject_ref = 'STRK' AND kind = 'notice')$q$),
        ('public.delivery_inflight',             $q$DELETE FROM public.delivery_inflight WHERE order_number LIKE 'STRK-TEST-%'$q$),
        ('public.delivery_dispatch',             $q$DELETE FROM public.delivery_dispatch WHERE order_number LIKE 'STRK-TEST-%'$q$),
        ('public.delivery_detail',               $q$DELETE FROM public.delivery_detail WHERE order_number LIKE 'STRK-TEST-%'$q$),
        ('public.delivery_summary',              $q$DELETE FROM public.delivery_summary WHERE order_number LIKE 'STRK-TEST-%'$q$),
        ('public.takeaway_summary',              $q$DELETE FROM public.takeaway_summary WHERE order_number LIKE 'STRK-TEST-%'$q$),
        ('public.order_item',                    $q$DELETE FROM public.order_item WHERE order_id IN
                                                     (SELECT order_id FROM public.food_order WHERE order_number LIKE 'STRK-TEST-%')$q$),
        ('public.food_order',                    $q$DELETE FROM public.food_order WHERE order_number LIKE 'STRK-TEST-%'$q$),
        ('public.debug_log',                     $q$DELETE FROM public.debug_log WHERE order_number LIKE 'STRK-TEST-%'$q$)
    ) AS v(tbl, stmt) LOOP
        IF to_regclass(s.tbl) IS NOT NULL THEN
            EXECUTE s.stmt;
        END IF;
    END LOOP;
END $$;

update rider_master
set is_in_shift = true,
    town = 'dummy',
    vehicle_type = 'bicycle'
where rider_name = 'Lohith';



INSERT INTO public.t_invites (rest_ref, phone_number, status, claimed_at, telegram_user_id, telegram_chat_id, telegram_first_name)
SELECT 'STRK', '447448440754', 'claimed', now(), telegram_user_id, telegram_chat_id, telegram_first_name
  FROM public.t_invites WHERE status = 'claimed' AND telegram_user_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM public.t_invites WHERE rest_ref = 'STRK' AND status = 'claimed')   -- once only: never add a second claim
 ORDER BY claimed_at DESC LIMIT 1;

-- ===== STAGE 1: NEW DELIVERY ORDER (notes, small-order fee, modifications, TEST3100 item) =====
-- Expect: the order card on Telegram (reminders at +15/+30/+45 s) and the WhatsApp confirmation prompt, both within ~5 s.
-- No rider job exists yet: like a real order, it is released to riders only after the restaurant accepted (STAGE 2b).
DO $$
DECLARE
    v_no      text := 'STRK-TEST-' || to_char(now() AT TIME ZONE 'UTC', 'HH24MISS');
    v_id      text := substr(v_no, strpos(v_no, '-') + 1);
    v_vehicle text;
    v_rest_id text;
    v_rest_name text;
BEGIN
    SELECT vehicle_type INTO v_vehicle FROM public.rider_master
     WHERE town = 'dummy' AND is_in_shift AND status = 'active' ORDER BY priority, id LIMIT 1;
    IF v_vehicle IS NULL THEN
        RAISE EXCEPTION 'STAGE 1: no active in-shift rider in town dummy (see PREREQUISITES)';
    END IF;
    SELECT rest_id, rest_name INTO v_rest_id, v_rest_name FROM public.restaurant_master WHERE rest_ref = 'STRK';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'STAGE 1: no restaurant_master row for rest_ref STRK (see PREREQUISITES)';
    ELSIF v_rest_id IS NULL THEN
        RAISE EXCEPTION 'STAGE 1: restaurant_master.rest_id is NULL for STRK. Give it one (once, see PREREQUISITES): UPDATE public.restaurant_master SET rest_id = ''STRK01'' WHERE rest_ref = ''STRK'' AND rest_id IS NULL;';
    END IF;

    -- The food order FIRST: the delivery_summary trigger reads it. payment_mode is derived from the TEST3100 item.
    PERFORM public.create_food_order_with_items(
        jsonb_build_object('order_id', v_id, 'order_number', v_no, 'recipient', '447448440754',
                           'notes', 'Please ring the bell twice (STRK test order)', 'thread_id', 'STRK-TEST-THREAD',
                           'action', 'delivery', 'total_price', 21.50, 'payment_status', 'test_no_payment',
                           'origin_channel', 'whatsapp', 'storefront', 'direct'),
        jsonb_build_array(
            jsonb_build_object('product_name', 'TEST3100',          'sku', 'TEST3100',  'quantity', 1, 'price', 1.00),
            jsonb_build_object('product_name', 'Chicken Shawarma',  'sku', 'STRK-SHW',  'quantity', 2, 'price', 8.50,
                               'modifications', jsonb_build_array('extra garlic sauce')),
            jsonb_build_object('product_name', 'Fries',             'sku', 'STRK-FRY',  'quantity', 1, 'price', 3.50)));
    UPDATE public.food_order
       SET small_order_fee = 1.00, final_order_value = 22.50, rest_cost = 15.00, service_charge = 0, delivery_fee = 0
     WHERE order_number = v_no;

    INSERT INTO public.delivery_summary (
        order_number, rest_id, rest_name, rest_lon, rest_lat, rest_address, town,
        customer_id, customer_name, customer_lon, customer_lat, customer_address,
        restaurant_confirmation_status, status, rest_confirmation_code, cust_confirmation_code, dtts)
    VALUES (
        v_no, v_rest_id, v_rest_name, 0.100950805301294, 51.3766272547284,
        '40b The Walnuts High Street Orpington BR6 0TW', 'dummy',
        '447448440754', 'Test Customer', 0.1008, 51.3764, '1 Test Street Orpington BR6 0TW',
        'restaurant_unconfirmed', 'restaurant_unconfirmed', 47, 70, now());
END $$;

SELECT s.order_number, s.town, s.restaurant_confirmation_status, s.status, f.payment_mode, f.payment_status,
       (SELECT count(*) FROM public.t_order_card_destinations('rest_admin', s.rest_ref)) AS telegram_destinations
  FROM public.delivery_summary s JOIN public.food_order f USING (order_number)
 WHERE s.order_number LIKE 'STRK-TEST-%';


-- ===== STAGE 2: ACCEPT + PICKUP TIME (you tap; this only shows the state) =====
-- Tap Accept and then a pickup time on Telegram or WhatsApp; status becomes 'unassigned'. Then run STAGE 2b, and expect
-- a dispatch offer on your dummy RIDER's WhatsApp.
SELECT order_number, restaurant_confirmation_status, status, restaurant_admin, pickup_time, pickup_time_initial
  FROM public.delivery_summary WHERE order_number LIKE 'STRK-TEST-%';
SELECT dispatch_id, rider_id, status, dtts FROM public.delivery_dispatch WHERE order_number LIKE 'STRK-TEST-%' ORDER BY dispatch_id;


-- ===== STAGE 2b: RELEASE TO RIDERS (run AFTER you accepted and chose a pickup time) =====
-- In production process_delivery() creates the delivery_detail row once the order is 'unassigned' (accepted, pickup time
-- set). This harness has no delivery_option rows, so this stage does that one step. Nothing is inserted until STAGE 2
-- shows status = 'unassigned'. Expect the dispatch offer on your dummy rider's WhatsApp within a few seconds.
INSERT INTO public.delivery_detail (order_number, customer_id, vehicle_type, town, rider_payout, distance, status)
SELECT s.order_number, s.customer_id,
       (SELECT vehicle_type FROM public.rider_master WHERE town = 'dummy' AND is_in_shift AND status = 'active' ORDER BY priority, id LIMIT 1),
       'dummy', 5.00, 1.5, 'unassigned'
  FROM public.delivery_summary s
 WHERE s.order_number LIKE 'STRK-TEST-%' AND s.status = 'unassigned' AND s.pickup_time IS NOT NULL
   AND (SELECT vehicle_type FROM public.rider_master WHERE town = 'dummy' AND is_in_shift AND status = 'active' ORDER BY priority, id LIMIT 1) IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM public.delivery_detail d WHERE d.order_number = s.order_number);
SELECT order_number, vehicle_type, town, status FROM public.delivery_detail WHERE order_number LIKE 'STRK-TEST-%';


-- ===== STAGE 3: RIDER ACCEPTS (you tap as the rider; this only shows the state) =====
-- Expect: the KITCHEN RECEIPT on WhatsApp AND Telegram (Telegram replies to the order card), shown with
-- Ready / +10 / +20 buttons, and the rider's chat starting its delivery graph.
SELECT i.dispatch_id, i.order_number, i.rider_id, d.status AS dispatch_status
  FROM public.delivery_inflight i JOIN public.delivery_dispatch d USING (dispatch_id) WHERE i.order_number LIKE 'STRK-TEST-%';
SELECT id, tcid, message_id, kind, card_status, state, dispatch_id FROM public.t_sent_messages
 WHERE subject_ref LIKE 'STRK-TEST-%' ORDER BY id;


-- ===== STAGE 4: READY / ADJUST (you tap) =====
-- Tap Ready on Telegram, +10 on WhatsApp, then Ready again on WhatsApp. Expect the rider nudged ONCE ("food ready"), the
-- Telegram copies redrawn within ~5 s ("Ready ... by <you>", pickup moved +10), the second Ready answered "Already marked
-- ready by ...". Race test (two dummy riders / two admins): tap Ready on both channels at the same moment -> one nudge.
SELECT order_number, ready_at, ready_by, ready_dispatch_id, pickup_time, pickup_time_initial, pickup_adjusted_by, pickup_adjusted_at
  FROM public.delivery_summary WHERE order_number LIKE 'STRK-TEST-%';
SELECT id, tcid, kind, card_status, state, taken_for, dispatch_id FROM public.t_sent_messages
 WHERE subject_ref LIKE 'STRK-TEST-%' AND kind = 'receipt' ORDER BY id;
SELECT * FROM public.t_receipts_stale('rest_admin');          -- empty once the 5-second job has caught up


-- ===== STAGE 5: RIDER PICKUP ALERTS (wait) =====
-- With pickup about 5 minutes after the order, job_rider_pickup_alerts fires its -10 / +2 / +7 checkpoints. Expect
-- the restaurant-admin alerts on WhatsApp AND Telegram (Telegram replies to the receipt).
SELECT dispatch_id, phase, audience, offset_minutes, status, due_dtts, sent_dtts
  FROM public.rider_pickup_alert WHERE order_number LIKE 'STRK-TEST-%' ORDER BY due_dtts, audience;


-- ===== STAGE 6: CANCEL + RE-DISPATCH (before pickup) =====
-- Uses the real function. Expect the old receipt copies to read "This rider is no longer on the job"; a new offer to your
-- dummy riders; when one accepts, a NEW receipt (the old copy in each chat is deleted) and Ready offered again.
SELECT public.dispatch_cancel_before_pickup(
           (SELECT dispatch_id FROM public.delivery_inflight WHERE order_number LIKE 'STRK-TEST-%' ORDER BY dispatch_id DESC LIMIT 1));


-- ===== STAGE 7: PICKED UP + COMPLETE =====
-- Either give the rider codes in the rider chat (the real tools), or force it here (two statements, run one at a time):
-- 7a. food collected -> the receipt becomes "Picked up by the rider"
UPDATE public.delivery_dispatch SET status = 'pickedup'
 WHERE dispatch_id = (SELECT dispatch_id FROM public.delivery_inflight WHERE order_number LIKE 'STRK-TEST-%' ORDER BY dispatch_id DESC LIMIT 1);
-- 7b. delivered -> "Delivered" notice on both channels, receipt becomes "Delivered HH:MM"
--     (dispatch_complete_func removes the inflight row, so run it only after 7a has shown on Telegram)
-- SELECT public.dispatch_complete_func(
--            (SELECT dispatch_id FROM public.delivery_dispatch WHERE order_number LIKE 'STRK-TEST-%' ORDER BY dispatch_id DESC LIMIT 1));


-- ===== STAGE 8: TAKEAWAY (payment_status 'test_no_payment': no payment call at all) =====
-- Expect the order card; accept + choose a pickup time; then the takeaway receipt on both channels with a Ready button;
-- Ready -> the customer event 'ready_for_collection' once. One overwatch "capture reconciliation" message is expected.
DO $$
DECLARE
    v_no text := 'STRK-TEST-' || to_char(now() AT TIME ZONE 'UTC', 'HH24MISS');
    v_id text := substr(v_no, strpos(v_no, '-') + 1);
    v_rest_id text;
    v_rest_name text;
BEGIN
    SELECT rest_id, rest_name INTO v_rest_id, v_rest_name FROM public.restaurant_master WHERE rest_ref = 'STRK';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'STAGE 8: no restaurant_master row for rest_ref STRK (see PREREQUISITES)';
    ELSIF v_rest_id IS NULL THEN
        RAISE EXCEPTION 'STAGE 8: restaurant_master.rest_id is NULL for STRK. Give it one (once, see PREREQUISITES): UPDATE public.restaurant_master SET rest_id = ''STRK01'' WHERE rest_ref = ''STRK'' AND rest_id IS NULL;';
    END IF;
    PERFORM public.create_food_order_with_items(
        jsonb_build_object('order_id', v_id, 'order_number', v_no, 'recipient', '447448440754',
                           'notes', 'Collection under Lohith (STRK test order)', 'thread_id', 'STRK-TEST-THREAD',
                           'action', 'takeaway', 'total_price', 21.50, 'payment_status', 'test_no_payment',
                           'origin_channel', 'whatsapp', 'storefront', 'direct'),
        jsonb_build_array(
            jsonb_build_object('product_name', 'TEST3100',         'sku', 'TEST3100', 'quantity', 1, 'price', 1.00),
            jsonb_build_object('product_name', 'Chicken Shawarma', 'sku', 'STRK-SHW', 'quantity', 2, 'price', 8.50,
                               'modifications', jsonb_build_array('extra garlic sauce')),
            jsonb_build_object('product_name', 'Fries',            'sku', 'STRK-FRY', 'quantity', 1, 'price', 3.50)));
    UPDATE public.food_order
       SET small_order_fee = 1.00, final_order_value = 22.50, rest_cost = 15.00, service_charge = 0, delivery_fee = 0
     WHERE order_number = v_no;
    INSERT INTO public.takeaway_summary (
        order_number, rest_id, rest_name, rest_address, town, customer_id, customer_name,
        restaurant_confirmation_status, status, rest_confirmation_code, dtts)
    VALUES (v_no, v_rest_id, v_rest_name, '40b The Walnuts High Street Orpington BR6 0TW', 'dummy',
            '447448440754', 'Test Customer', 'restaurant_unconfirmed', 'restaurant_unconfirmed', 47, now());
END $$;
SELECT order_number, town, status, pickup_time, ready_at, ready_by FROM public.takeaway_summary WHERE order_number LIKE 'STRK-TEST-%';


-- ===== STAGE 8b: TAKEAWAY, PAY AT RESTAURANT (optional: ONE print-only request to the TEST payment service) =====
-- Same as STAGE 8 but payment_status 'pay_at_rest', so the receipt shows "Pay at restaurant - collect GBP 21.50".
DO $$
DECLARE
    v_no text := 'STRK-TEST-' || to_char(now() AT TIME ZONE 'UTC', 'HH24MISS');
    v_id text := substr(v_no, strpos(v_no, '-') + 1);
    v_rest_id text;
    v_rest_name text;
BEGIN
    SELECT rest_id, rest_name INTO v_rest_id, v_rest_name FROM public.restaurant_master WHERE rest_ref = 'STRK';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'STAGE 8b: no restaurant_master row for rest_ref STRK (see PREREQUISITES)';
    ELSIF v_rest_id IS NULL THEN
        RAISE EXCEPTION 'STAGE 8b: restaurant_master.rest_id is NULL for STRK. Give it one (once, see PREREQUISITES): UPDATE public.restaurant_master SET rest_id = ''STRK01'' WHERE rest_ref = ''STRK'' AND rest_id IS NULL;';
    END IF;
    PERFORM public.create_food_order_with_items(
        jsonb_build_object('order_id', v_id, 'order_number', v_no, 'recipient', '447448440754',
                           'notes', 'Pay at the counter (STRK test order)', 'thread_id', 'STRK-TEST-THREAD',
                           'action', 'takeaway', 'total_price', 21.50, 'payment_status', 'pay_at_rest',
                           'origin_channel', 'whatsapp', 'storefront', 'direct'),
        jsonb_build_array(
            jsonb_build_object('product_name', 'TEST3100',         'sku', 'TEST3100', 'quantity', 1, 'price', 1.00),
            jsonb_build_object('product_name', 'Chicken Shawarma', 'sku', 'STRK-SHW', 'quantity', 2, 'price', 8.50,
                               'modifications', jsonb_build_array('extra garlic sauce')),
            jsonb_build_object('product_name', 'Fries',            'sku', 'STRK-FRY', 'quantity', 1, 'price', 3.50)));
    UPDATE public.food_order
       SET small_order_fee = 1.00, final_order_value = 22.50, rest_cost = 15.00, service_charge = 0, delivery_fee = 0
     WHERE order_number = v_no;
    INSERT INTO public.takeaway_summary (
        order_number, rest_id, rest_name, rest_address, town, customer_id, customer_name,
        restaurant_confirmation_status, status, rest_confirmation_code, dtts)
    VALUES (v_no, v_rest_id, v_rest_name, '40b The Walnuts High Street Orpington BR6 0TW', 'dummy',
            '447448440754', 'Test Customer', 'restaurant_unconfirmed', 'restaurant_unconfirmed', 47, now());
END $$;
SELECT order_number, town, status, pickup_time FROM public.takeaway_summary WHERE order_number LIKE 'STRK-TEST-%';


-- ===== STAGE 9: TIMEOUT (auto-accept notice) =====
-- A delivery order whose clock started an hour ago, with NO delivery_detail (so nothing is dispatched). Expect the next
-- timeout sweep to auto-accept it: the auto-accept notice on WhatsApp AND Telegram (replying to the order card), sent
-- after the update, and the card turning to "Auto-accepted".
DO $$
DECLARE
    v_no text := 'STRK-TEST-' || to_char(now() AT TIME ZONE 'UTC', 'HH24MISS');
    v_id text := substr(v_no, strpos(v_no, '-') + 1);
    v_rest_id text;
    v_rest_name text;
BEGIN
    SELECT rest_id, rest_name INTO v_rest_id, v_rest_name FROM public.restaurant_master WHERE rest_ref = 'STRK';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'STAGE 9: no restaurant_master row for rest_ref STRK (see PREREQUISITES)';
    ELSIF v_rest_id IS NULL THEN
        RAISE EXCEPTION 'STAGE 9: restaurant_master.rest_id is NULL for STRK. Give it one (once, see PREREQUISITES): UPDATE public.restaurant_master SET rest_id = ''STRK01'' WHERE rest_ref = ''STRK'' AND rest_id IS NULL;';
    END IF;
    PERFORM public.create_food_order_with_items(
        jsonb_build_object('order_id', v_id, 'order_number', v_no, 'recipient', '447448440754',
                           'notes', 'Timeout test (STRK test order)', 'thread_id', 'STRK-TEST-THREAD',
                           'action', 'delivery', 'total_price', 21.50, 'payment_status', 'test_no_payment',
                           'origin_channel', 'whatsapp', 'storefront', 'direct'),
        jsonb_build_array(
            jsonb_build_object('product_name', 'TEST3100', 'sku', 'TEST3100', 'quantity', 1, 'price', 1.00),
            jsonb_build_object('product_name', 'Fries',    'sku', 'STRK-FRY', 'quantity', 1, 'price', 3.50)));
    UPDATE public.food_order SET final_order_value = 4.50, rest_cost = 3.00, service_charge = 0, delivery_fee = 0 WHERE order_number = v_no;
    INSERT INTO public.delivery_summary (
        order_number, rest_id, rest_name, rest_lon, rest_lat, rest_address, town,
        customer_id, customer_name, customer_lon, customer_lat, customer_address,
        restaurant_confirmation_status, status, rest_confirmation_code, cust_confirmation_code, dtts)
    VALUES (
        v_no, v_rest_id, v_rest_name, 0.100950805301294, 51.3766272547284,
        '40b The Walnuts High Street Orpington BR6 0TW', 'dummy',
        '447448440754', 'Test Customer', 0.1008, 51.3764, '1 Test Street Orpington BR6 0TW',
        'restaurant_unconfirmed', 'restaurant_unconfirmed', 47, 70, now() - interval '1 hour');
END $$;
SELECT order_number, restaurant_confirmation_status, status, pickup_time FROM public.delivery_summary WHERE order_number LIKE 'STRK-TEST-%';


-- ===== STAGE 10: RESTAURANT FEEDBACK (run from a terminal, not SQL) =====
-- Expect the feedback notice on WhatsApp AND Telegram (no order card to reply to).
--   curl -X POST "$ORDELO_APP_URL/customer-hooks/restaurant-feedback" -H 'Content-Type: application/json' \
--        -d '{"rest_ref": "STRK", "cust_id": "447448440754", "cust_name": "Test Customer", "description": "Test feedback from the STRK harness"}'
-- (the exact body fields are in watomation/routers/customer_hooks.py, submit_restaurant_feedback)


-- ---------------------------------------------------------------------------------------------
-- WATCH IT (any time)
-- ---------------------------------------------------------------------------------------------
--   Ready / adjust bookkeeping:  SELECT order_number, ready_at, ready_by, ready_dispatch_id, pickup_time, pickup_time_initial,
--                                       pickup_adjusted_by FROM public.delivery_summary WHERE order_number LIKE 'STRK-TEST-%';
--   Every Telegram copy:         SELECT id, tcid, message_id, kind, card_status, state, taken_for, close_reason, dispatch_id
--                                  FROM public.t_sent_messages WHERE subject_ref LIKE 'STRK-TEST-%' OR (subject_type = 'rest' AND subject_ref = 'STRK')
--                                 ORDER BY id;          -- kind: order_card | receipt | notice
--   Copies waiting for the sweep: SELECT * FROM public.t_receipts_stale('rest_admin');
--   Customer events:             SELECT order_number, event_key, event_type, occurred_at FROM public.order_customer_event WHERE order_number LIKE 'STRK-TEST-%';
--   Your taps as the bot saw them: SELECT update_id, kind, tuid, status, error, received_at FROM public.t_inbox ORDER BY received_at DESC LIMIT 10;
--   Who is linked:               SELECT * FROM public.t_order_card_destinations('rest_admin', 'STRK');
