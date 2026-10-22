-- =============================================================================================
-- TEST HARNESS (not a migration): Telegram breaks and locations for riders, alert pauses for restaurant admins (phases
-- R5-R6 of plans/telegram-rider-bot-plan.md): /shift, /off, /on, the "ends soon" / "back on" messages, a location shared
-- in Telegram, the restaurant bot's /off and /on with the last-admin guard, and the WhatsApp side left as it was.
-- =============================================================================================
-- Run it ONE STAGE AT A TIME in the Supabase SQL editor; every stage can be repeated. Stages that say "you" are actions in
-- Telegram or WhatsApp; the queries only show what the database says afterwards. It works with test_rider_telegram_jobs.sql
-- (your rider row) and test_restaurant_notices.sql (the fake STRK-TEST orders) for the stages that need a job or an order.
--
-- WHAT IT TOUCHES
--   update        pauses: ONLY rows whose principal is your phone 447448440754: STAGE 0 and STAGE 10 end them ('operator'),
--                 STAGE 3 and STAGE 8 move the end of your open pause to 2 minutes from now (so the messages come quickly)
--   read          rider_master, restaurant_master, t_invites, pauses, ordelo_config, wa_location_request,
--                 wa_location_observation, delivery_dispatch, cron.job
-- It deletes and inserts nothing, and sends no message itself (the app and the pg_cron job 'job_pause_sweep' do).
--
-- PREREQUISITES (the check below shows each)
--   * migrations/rider_telegram_r5_r6.sql steps 1-6 applied (VERIFY true / 7 / true / true / 4 / 0, VERIFY 2: 1) and the R5-R6
--     code deployed; both command menus re-published (rider: /shift /off /on; restaurant: /off /on).
--   * Your rider row as for test_rider_telegram_jobs.sql: linked on Telegram, status 'active', town 'dummy', in overwatch_list.
--   * For STAGE 7-8: your phone in restaurant_master.admins for STRK and your Telegram chat linked to STRK (a claimed invite).
--     A restaurant with ONE admin can never pause that admin (the last-admin guard): with only you in STRK.admins, STAGE 7
--     shows the refusal; to see a pause succeed you need a second phone in STRK.admins (an owner decision; see STAGE 7).
--   * ORDELO_APP_URL pointing at the instance under test (the sweep POSTs /pause-hooks/sweep there).
-- Offline proof of this script: tests/sql/test_rider_pauses_and_locations_script_sql.py (isolated database).
-- =============================================================================================

-- ===== PREREQUISITES CHECK (read only) =====
SELECT
    (SELECT count(*) FROM pg_proc WHERE proname IN ('pause_options', 'rider_set_shift', 't_alert_destinations', 't_admin_pause',
                                                    't_admin_resume', 't_admin_pause_status', 't_admin_pause_chats'))  AS r5_r6_functions,   -- 7
    (SELECT count(*) FROM cron.job WHERE jobname = 'job_pause_sweep')                                   AS sweep_job,         -- 1
    (SELECT channel || ' / ' || status || ' / ' || town || ' / in_shift ' || is_in_shift
       FROM public.rider_master WHERE rider_id = '447448440754')                                       AS your_rider,        -- telegram / active / dummy / in_shift true
    (SELECT config_value FROM public.ordelo_config WHERE config_key = 'PAUSE_DURATIONS_RIDER')         AS rider_lengths,     -- 6h,1d,3d
    (SELECT coalesce(cardinality(admins), 0) FROM public.restaurant_master WHERE rest_ref = 'STRK')    AS strk_admins,       -- 1 = guard demo only; 2+ = pause can succeed
    (SELECT count(*) FROM public.t_invites WHERE rest_ref = 'STRK' AND status = 'claimed'
        AND phone_number = '447448440754')                                                             AS your_strk_link;    -- >= 1

-- ===== STAGE 0: RESET your open pauses (rider and restaurant admin; ends them, deletes nothing) =====
UPDATE public.pauses
   SET ended_at = now(), end_reason = 'operator', announced_at = now()
 WHERE principal = '447448440754'
   AND ended_at IS NULL;
SELECT count(*) AS your_open_pauses FROM public.pauses WHERE principal = '447448440754' AND ended_at IS NULL;  -- 0

-- ===== STAGE 1: /shift in @ByteloopRidersBot (you) =====
-- Expect: "🟢 On: new job offers arrive here. Send /off to take a break."
SELECT status, is_in_shift, channel, public.is_paused('rider', rider_id, NULL) AS paused
  FROM public.rider_master WHERE rider_id = '447448440754';  -- active | true | telegram | false

-- ===== STAGE 2: /off, then tap "6 hours" (you) =====
-- Expect: the question turns into "⏸ On a break until <time>. No new job offers until then. Send /on to come back early."
-- /shift now says "⏸ On a break until <time>". Optional: run test_restaurant_notices.sql STAGE 0-2b: no offer reaches you.
SELECT pause_id, audience, starts_at, ends_at, created_via, created_by
  FROM public.pauses WHERE principal = '447448440754' AND audience = 'rider' AND ended_at IS NULL;  -- one row, ends in 6 h, telegram
SELECT public.is_paused('rider', '447448440754', NULL) AS paused_now;  -- true

-- ===== STAGE 3: the "ends soon" message (moves YOUR open break's end to 2 minutes from now) =====
UPDATE public.pauses
   SET ends_at = now() + interval '2 minutes', reminded_at = NULL
 WHERE principal = '447448440754' AND audience = 'rider' AND ended_at IS NULL;
-- Within a minute (job_pause_sweep runs every minute): "⏰ Your break ends at <time>. Job offers start again after that."
SELECT ends_at, reminded_at FROM public.pauses
 WHERE principal = '447448440754' AND audience = 'rider' ORDER BY pause_id DESC LIMIT 1;  -- reminded_at set after the message

-- ===== STAGE 4: the "back on" message (wait ~3 minutes after STAGE 3) =====
-- Expect: "✅ Your break is over. You're back on and will get job offers again." (no job had to switch you on: is_paused()
-- turned false at ends_at; the sweep only closed the row and sent the message)
SELECT ended_at IS NOT NULL AS closed, end_reason, announced_at IS NOT NULL AS announced
  FROM public.pauses WHERE principal = '447448440754' AND audience = 'rider' ORDER BY pause_id DESC LIMIT 1;  -- true | expired | true
SELECT public.is_paused('rider', '447448440754', NULL) AS paused_now;  -- false

-- ===== STAGE 5: /off (tap "1 day"), then /on (you) =====
-- Expect: "⏸ On a break until <tomorrow ...>", then "✅ Break over: you're back on. New job offers will arrive here."
SELECT end_reason, announced_at IS NOT NULL AS announced
  FROM public.pauses WHERE principal = '447448440754' AND audience = 'rider' ORDER BY pause_id DESC LIMIT 1;  -- resumed | true

-- ===== STAGE 6: a location shared in Telegram (needs a job: test_rider_telegram_jobs.sql STAGE 0-2, you accept) =====
-- Ask for the rider's location: as the customer on WhatsApp after pickup ("where is my rider?", restaurant-agents), or as the
-- STRK admin with POST /wa-request-location (Swagger; location_requested_by 'restaurant_admin', requester_id your phone).
-- Expect in Telegram: "Please share your current location ..." with [📍 Share current location]; tap it; the agent says it
-- was sent; the requester gets the pin labelled as the rider's latest location (source sent as 'whatsapp_current').
SELECT r.status, r.wa_request_message_id, o.source, o.wa_inbound_message_id
  FROM public.wa_location_request r LEFT JOIN public.wa_location_observation o ON o.observation_id = r.observation_id
 WHERE r.rider_id = '447448440754' AND r.order_number LIKE 'STRK-TEST-%' ORDER BY r.wa_location_req_time DESC LIMIT 3;
-- delivered (or fulfilled) | tg:<chat>:<prompt id> | telegram_current | tg:<chat>:<your share id>
-- A live location or a picked place is refused ("Please use the 📍 Share current location button"); a share with no request
-- open gets "Thanks. No location was requested right now."

-- ===== STAGE 7: the restaurant bot: /off and the last-admin guard (you, as STRK admin) =====
-- With ONLY you in STRK.admins: tap any length -> "🔔 Strikers: not paused. You're the only admin left getting its alerts."
-- With a second phone in STRK.admins (owner decision; this script never changes restaurant_master), e.g.:
--   UPDATE public.restaurant_master SET admins = array_append(admins, '<second phone>') WHERE rest_ref = 'STRK' RETURNING admins;
-- tap "6 hours" -> "⏸ Strikers: paused until <time>"; then test_restaurant_notices.sql STAGE 0-1: NO new order card in your
-- Telegram (WhatsApp still gets the order), while a card already in your chat keeps updating and its buttons still work.
SELECT (SELECT count(*) FROM public.t_alert_destinations('rest_admin', 'STRK') WHERE phone = '447448440754')       AS new_alerts_to_you,  -- 0 while paused
       (SELECT count(*) FROM public.t_order_card_destinations('rest_admin', 'STRK') WHERE phone = '447448440754')  AS may_see_and_tap,    -- >= 1
       public.is_paused('rest_admin', '447448440754', 'STRK')                                                       AS paused;             -- true while paused

-- ===== STAGE 8: the restaurant bot's "starts again soon" and "back on" (moves YOUR open admin pause's end to 2 minutes) =====
UPDATE public.pauses
   SET ends_at = now() + interval '2 minutes', reminded_at = NULL
 WHERE principal = '447448440754' AND audience = 'rest_admin' AND ended_at IS NULL;
-- Within a minute: "⏰ Order alerts for Strikers start again at <time>."; ~3 minutes later: "🔔 Order alerts for Strikers are back on."
-- (/on on the restaurant bot ends it at once instead: "🔔 Strikers: alerts back on")
SELECT scope, ends_at, reminded_at IS NOT NULL AS reminded, end_reason, announced_at IS NOT NULL AS announced
  FROM public.pauses WHERE principal = '447448440754' AND audience = 'rest_admin' ORDER BY pause_id DESC LIMIT 1;

-- ===== STAGE 9: WhatsApp unchanged (read only) =====
-- Who the 11:00 shift question goes to now (the WHERE of enquire_shift_availability()): WhatsApp riders only.
SELECT rider_id, rider_name FROM public.rider_master WHERE status = 'active' AND channel = 'whatsapp' ORDER BY rider_id;  -- you are NOT listed
-- You (a Telegram rider, no job) send "hi" to the Ordelo WhatsApp number -> "Your rider messages are on Telegram now: ..."
-- A WhatsApp rider answering the shift question "Yes" / "No" gets the same texts as before.

-- ===== STAGE 10: CLEAN UP (ends your open pauses; restaurant_master is yours to restore if you changed it in STAGE 7) =====
UPDATE public.pauses
   SET ended_at = now(), end_reason = 'operator', announced_at = now()
 WHERE principal = '447448440754'
   AND ended_at IS NULL;
SELECT count(*) AS your_open_pauses FROM public.pauses WHERE principal = '447448440754' AND ended_at IS NULL;  -- 0
-- If you added a second STRK admin in STAGE 7:
--   UPDATE public.restaurant_master SET admins = array_remove(admins, '<second phone>') WHERE rest_ref = 'STRK' RETURNING admins;
