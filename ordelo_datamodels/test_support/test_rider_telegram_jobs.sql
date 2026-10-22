-- =============================================================================================
-- TEST HARNESS (not a migration): a rider job on TELEGRAM end to end (phases R2-R4 of plans/telegram-rider-bot-plan.md):
-- the offer, Accept, the job card, the rider agent in Telegram, completion, and the other riders' offers being closed.
-- =============================================================================================
-- It works TOGETHER with test_restaurant_notices.sql, which creates the fake STRK-TEST-* order and releases it to riders
-- (its STAGE 0, 1, 2 and 2b). This script only prepares YOUR rider row, shows the state after each thing you do, and
-- resets your threads. Run it ONE STAGE AT A TIME in the Supabase SQL editor; every stage can be repeated.
--
-- WHAT IT TOUCHES
--   update        rider_master: ONLY your row (rider_id 447448440754) in STAGE 0b (status, town, is_in_shift) and STAGE 9 (channel)
--   update        thread: STAGE 0 closes (is_active = false) the rider threads of STRK-TEST-* dispatches; nothing is deleted
--   read          delivery_dispatch, delivery_summary, delivery_inflight, thread, ordelo_config
-- It deletes nothing (test_restaurant_notices.sql STAGE 0 removes the fake orders) and sends no message itself.
--
-- PREREQUISITES (the check below shows each)
--   * migrations/rider_telegram_r2_r4.sql applied (3 / 1 / 6) and the R2-R4 code deployed, rider webhook registered,
--     the rider bot's command menu published (/job included; notebooks/telegram/tgram_setup_bot.py with BOT_KEY = 'rider').
--   * Your phone linked in @ByteloopRidersBot (/start -> Share my phone number): channel 'telegram', tcid set.
--   * Your rider_id in ordelo_config 'overwatch_list' (fake orders carry the TEST3100 item: offered to overwatch riders only).
--   * Optional, for STAGE 6: a second overwatch rider in town 'dummy' (a second phone, on WhatsApp or Telegram).
-- Offline proof of this script: tests/sql/test_rider_telegram_jobs_script_sql.py (isolated database).
-- =============================================================================================

-- ===== PREREQUISITES CHECK (read only) =====
SELECT
    (SELECT count(*) FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = 'delivery_dispatch'
        AND column_name IN ('channel', 'channel_msg_ref', 'thread_id'))                           AS dispatch_columns,  -- 3
    (SELECT count(*) FROM pg_trigger WHERE tgname = 'trigger_delivery_dispatch_stamp_channel')   AS stamp_trigger,     -- 1
    (SELECT count(*) FROM pg_proc WHERE proname IN ('rider_thread_id', 'rider_thread_open', 'rider_thread_touch',
                                                    'rider_thread_active', 'rider_thread_describe', 'rider_thread_close')) AS thread_functions, -- 6
    (SELECT channel || ' / tcid ' || coalesce(tcid::text, 'NULL') || ' / ' || status || ' / ' || town || ' / in_shift ' || is_in_shift
       FROM public.rider_master WHERE rider_id = '447448440754')                                 AS your_rider,        -- telegram / tcid <n> / ...
    (SELECT config_value LIKE '%447448440754%' FROM public.ordelo_config WHERE config_key = 'overwatch_list') AS you_are_overwatch; -- true

-- ===== STAGE 0: RESET your rider threads of earlier fake orders (closes them; deletes nothing) =====
-- Run it BEFORE test_restaurant_notices.sql STAGE 0 (which deletes the fake dispatches and with them the link to the thread).
UPDATE public.thread t
   SET is_active = FALSE
  FROM public.delivery_dispatch d
 WHERE d.thread_id = t.thread_id
   AND d.order_number LIKE 'STRK-TEST-%'
   AND t.is_active IS TRUE;
SELECT count(*) AS open_fake_job_threads
  FROM public.thread t JOIN public.delivery_dispatch d ON d.thread_id = t.thread_id
 WHERE d.order_number LIKE 'STRK-TEST-%' AND t.is_active;  -- 0

-- ===== STAGE 0b: prepare YOUR rider row (only 447448440754; note the "before" row to restore it later) =====
SELECT rider_id, status, town, vehicle_type, is_in_shift, channel FROM public.rider_master WHERE rider_id = '447448440754';  -- before
UPDATE public.rider_master
   SET status = 'active', town = 'dummy', is_in_shift = TRUE
 WHERE rider_id = '447448440754';
SELECT rider_id, status, town, vehicle_type, is_in_shift, channel, tcid IS NOT NULL AS linked
  FROM public.rider_master WHERE rider_id = '447448440754';  -- active | dummy | <vehicle> | true | telegram | true
-- Now run test_restaurant_notices.sql STAGE 0, STAGE 1, STAGE 2 (accept as the restaurant) and STAGE 2b.

-- ===== STAGE 1: the OFFER arrived in Telegram (after test_restaurant_notices.sql STAGE 2b, within ~10 s) =====
-- Expect in @ByteloopRidersBot: the offer (distance, payout, pickup time, addresses) with Accept / Decline buttons.
SELECT dispatch_id, rider_id, status, channel, channel_msg_ref, thread_id
  FROM public.delivery_dispatch WHERE order_number LIKE 'STRK-TEST-%' ORDER BY dispatch_id DESC;
-- your row: unassigned | telegram | tg:<your tcid>:<message id> | NULL      (a WhatsApp rider's row: whatsapp | wamid...)

-- ===== STAGE 2: you tap ACCEPT =====
-- Expect: the offer turns into "Accepted · ... Waiting for confirmation…", then within ~5 s "✅ The job is yours", followed
-- by the job card (Pickup Location / Dropoff Location / Contact Customer) and the pickup-time heads-up.
SELECT d.dispatch_id, d.status, d.thread_id, t.is_active AS thread_open, t.last_access_dtts
  FROM public.delivery_dispatch d LEFT JOIN public.thread t ON t.thread_id = d.thread_id
 WHERE d.order_number LIKE 'STRK-TEST-%' AND d.rider_id = '447448440754' ORDER BY d.dispatch_id DESC;
-- assigned | ORDELO-dispatch-<dispatch_id> | true | just now
SELECT public.rider_thread_active('ORDELO', '447448440754', FALSE) AS your_open_thread;
-- {"result": "active", "thread_id": "ORDELO-dispatch-<id>", "channel": "telegram", "order_number": "STRK-TEST-...", ...}

-- ===== STAGE 3: talk to the agent in TELEGRAM (you) =====
-- Tap "Pickup Location" on the job card            -> a map pin of the restaurant, in Telegram
-- Send "where do I go?"                            -> the agent answers in Telegram (typing… first; up to ~20 s)
-- Send /job                                        -> "Current job: STRK-TEST-..." with pickup and drop-off
-- Send "hello" to the Ordelo WhatsApp number       -> "Your current job *STRK-TEST-...* is on Telegram. Please reply there."
SELECT thread_id, is_active, last_access_dtts FROM public.thread
 WHERE thread_id = (SELECT thread_id FROM public.delivery_dispatch
                     WHERE order_number LIKE 'STRK-TEST-%' AND rider_id = '447448440754' ORDER BY dispatch_id DESC LIMIT 1);
-- true | refreshed by every message (the stale-thread job closes it only after THREAD_INACTIVE_TIME_INTERVAL idle)

-- ===== STAGE 4: the confirmation codes (send them to the bot as text) =====
SELECT order_number, rest_confirmation_code, cust_confirmation_code
  FROM public.delivery_summary WHERE order_number LIKE 'STRK-TEST-%' ORDER BY order_number DESC LIMIT 1;
-- Send the restaurant code -> ✅ and the drop-off pin; then the customer code -> ✅ "Delivery completed"
SELECT d.status AS dispatch_status, t.is_active AS thread_open
  FROM public.delivery_dispatch d JOIN public.thread t ON t.thread_id = d.thread_id
 WHERE d.order_number LIKE 'STRK-TEST-%' AND d.rider_id = '447448440754' ORDER BY d.dispatch_id DESC LIMIT 1;
-- completed | false          (after completion: text to the bot gets "No active job. Use /job to check, or /help.")

-- ===== STAGE 5: a wrong tap after the job (you) =====
-- Tap "Pickup Location" on the old job card -> a small "This job is expired." notice, no agent turn.
-- Tap Accept on any old offer               -> it is redrawn as "This job is no longer available" (or "Taken by another rider").
SELECT count(*) AS your_open_threads FROM public.thread WHERE recipient = '447448440754' AND agent = 'ORDELO' AND is_active;  -- 0

-- ===== STAGE 6: two riders, one job (needs the optional second overwatch rider) =====
-- Repeat test_restaurant_notices.sql STAGE 0-2b; BOTH riders get the offer; the second rider taps Accept first, then you.
SELECT dispatch_id, rider_id, status, channel, channel_msg_ref IS NOT NULL AS has_ref
  FROM public.delivery_dispatch WHERE order_number LIKE 'STRK-TEST-%' ORDER BY dispatch_id;
-- winner: assigned | the other: missed (Telegram: the offer now reads "❌ Taken by another rider", buttons gone;
-- WhatsApp: the usual "Sorry, the order was picked up by another rider" text, unchanged)

-- ===== STAGE 7: nobody accepts (the order times out) =====
-- Repeat test_restaurant_notices.sql STAGE 0-2b and leave the offer alone until the delivery timeout passes
-- (ordelo_config STRK_DELIVERY_TIMEOUT_TIME). Expect the Telegram offer to read "⌛ Offer expired", buttons gone.
SELECT order_number, status FROM public.delivery_summary WHERE order_number LIKE 'STRK-TEST-%' ORDER BY order_number DESC LIMIT 1;  -- timedout

-- ===== STAGE 8: decline your own assigned job before pickup (optional) =====
-- On Telegram the accepted offer has no buttons left, so a rider cancels by asking the agent. Accept a fresh offer
-- (STAGE 2), then send "I need to cancel this job" in Telegram -> the agent asks for a reason and cancels before pickup.
SELECT dispatch_id, status, reason_for_decline FROM public.delivery_dispatch
 WHERE order_number LIKE 'STRK-TEST-%' AND rider_id = '447448440754' ORDER BY dispatch_id DESC LIMIT 1;  -- declined | <your reason>

-- ===== STAGE 9: back to WhatsApp, if you want (manual; your Telegram link is kept) =====
-- UPDATE public.rider_master SET channel = 'whatsapp' WHERE rider_id = '447448440754' RETURNING rider_id, channel, tcid;
-- New offers then go to WhatsApp; a job that started on Telegram stays there until it ends (the channel is fixed per dispatch).
-- Restore status / town / is_in_shift from the "before" row of STAGE 0b if you changed them.
