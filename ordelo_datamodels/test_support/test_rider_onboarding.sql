-- =============================================================================================
-- TEST HARNESS (not a migration): exercise the rider bot onboarding functions, the pauses and the R1 dispatch gate on the
-- REAL database with FAKE riders, after migrations/rider_telegram_r1.sql has been applied (phase R1).
-- =============================================================================================
-- Run it ONE STAGE AT A TIME in the Supabase SQL editor (each block starts with "-- ===== STAGE n ... =====").
-- Every stage can be repeated. STAGE 0 wipes the earlier fake rows first, so start there. Each stage ends with a SELECT
-- whose comments say what you should see.
--
-- WHAT IT TOUCHES (and only these rows)
--   rider_master  rows whose rider_id starts with 4477009008 (Ofcom's drama range 07700 900xxx: never a real phone)
--   pauses        rows whose principal starts with 4477009008
--   Fake Telegram ids 999000000801..999000000899 (far above any id Telegram hands out to people today).
--   delete        STAGE 0 deletes ONLY those fake rows (the harness's own; nothing else is ever deleted).
-- It only READS everything else. It sends NO Telegram or WhatsApp message: the functions write rows, the bot is not involved
-- until STAGE 8, which is a manual test with your own phone and its own undo.
-- The fake riders use town 'dummy' (the existing test town) and stay status 'inactive' except in STAGE 7, so they are never
-- offered a real order; while they exist, 'dummy' / 'bike' also appear in t_rider_choices() for real sign-ups. Run STAGE 0
-- again when you are done.
--
-- PREREQUISITES: migrations/rider_telegram_r1.sql steps 1-5 applied. The check below must show 7 / 10 / true.
-- Offline proof of this script: tests/sql/test_rider_onboarding_script_sql.py (isolated database).
-- =============================================================================================

-- ===== PREREQUISITES CHECK (read only) =====
SELECT
    (SELECT count(*) FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = 'rider_master'
        AND column_name IN ('channel', 'tuid', 'tcid', 't_username', 't_first_name', 't_linked_at', 'phone_verified')) AS new_columns,  -- 7
    (SELECT count(*) FROM pg_proc
      WHERE proname IN ('t_rider_link', 't_rider_set_profile', 't_rider_choices', 't_rider_profile', 't_rider_phone_digits',
                        'is_paused', 'pause_start', 'pause_end', 'pause_current', 'pause_duration'))                            AS functions,    -- 10
    (SELECT prosrc LIKE '%is_paused%' AND prosrc LIKE '%status = ''active''%' FROM pg_proc WHERE proname = 'get_available_riders') AS dispatch_gate; -- true

-- ===== STAGE 0: RESET (deletes ONLY the harness's own fake rows) =====
DELETE FROM public.pauses WHERE principal LIKE '4477009008%';
DELETE FROM public.rider_master WHERE rider_id LIKE '4477009008%' OR tuid BETWEEN 999000000801 AND 999000000899;
SELECT count(*) AS fake_riders_left FROM public.rider_master WHERE rider_id LIKE '4477009008%';  -- 0

-- ===== STAGE 1: an EXISTING rider links Telegram for the first time =====
INSERT INTO public.rider_master (rider_id, rider_name, vehicle_type, town, status, is_in_shift)
VALUES ('447700900801', 'Harness Existing', 'bike', 'dummy', 'inactive', false)
ON CONFLICT (rider_id) DO NOTHING;
SELECT public.t_rider_link(999000000801, 999000000801, '+44 7700 900801', 'harness_a', 'Harness') ->> 'result' AS result;  -- linked
SELECT rider_id, channel, tuid, tcid, phone_verified, is_in_shift
  FROM public.rider_master WHERE rider_id = '447700900801';  -- telegram | 999000000801 | 999000000801 | true | true

-- ===== STAGE 2: the same person runs /start again (refresh) =====
SELECT public.t_rider_link(999000000801, -100801, '447700900801', 'harness_a2', 'Harness') ->> 'result' AS result;  -- already_linked
SELECT tcid, t_username FROM public.rider_master WHERE rider_id = '447700900801';  -- -100801 | harness_a2

-- ===== STAGE 3: a NEW Telegram account shares the same phone (new handset): the link moves =====
SELECT public.t_rider_link(999000000802, 999000000802, '447700900801', 'harness_b', 'Harness') AS out;
-- out.result = relinked, out.previous_tuid = 999000000801, out.previous_username = harness_a2
SELECT tuid FROM public.rider_master WHERE rider_id = '447700900801';  -- 999000000802

-- ===== STAGE 4: that account tries ANOTHER rider's phone: refused =====
INSERT INTO public.rider_master (rider_id, rider_name, vehicle_type, town, status, is_in_shift)
VALUES ('447700900803', 'Harness Other', 'bike', 'dummy', 'inactive', false)
ON CONFLICT (rider_id) DO NOTHING;
SELECT public.t_rider_link(999000000802, 999000000802, '447700900803', 'harness_b', 'Harness') AS out;  -- {"result": "tuid_taken", "rider_id": "447700900801"}
SELECT tuid FROM public.rider_master WHERE rider_id = '447700900803';  -- NULL (untouched)

-- ===== STAGE 5: an UNKNOWN phone signs up, then picks town and vehicle =====
SELECT public.t_rider_link(999000000804, 999000000804, '447700900804', 'harness_new', 'Newbie') AS out;
-- out.result = registered, out.status = inactive, out.needs_profile = true
SELECT public.t_rider_choices() AS choices;  -- the real towns and vehicles (plus 'dummy' / 'bike' from this harness)
SELECT public.t_rider_set_profile(999000000804, 'dummy', NULL) AS out;   -- {"result": "ok", "town": "dummy", "vehicle_type": "TBD", "needs_profile": true}
SELECT public.t_rider_set_profile(999000000804, NULL, 'bike') AS out;    -- {"result": "ok", ..., "needs_profile": false}
SELECT public.t_rider_set_profile(999000000804, 'Atlantis', NULL) ->> 'result' AS result;  -- bad_town
SELECT rider_id, rider_name, status, town, vehicle_type, channel, phone_verified
  FROM public.rider_master WHERE rider_id = '447700900804';  -- Newbie | inactive | dummy | bike | telegram | true

-- ===== STAGE 6: pauses (what the rider bot's /off and /on call since phase R5) =====
SELECT public.pause_start('rider', '447700900801', NULL, '6h', 'operator', 'harness') ->> 'result' AS result;  -- paused
SELECT public.is_paused('rider', '447700900801', NULL) AS paused;                                           -- true
SELECT public.pause_start('rider', '447700900801', NULL, '1d', 'operator', 'harness') AS out;               -- result extended, ends_at about 24 h from now
SELECT public.pause_start('rider', '447700900801', NULL, '7h', 'operator', 'harness') ->> 'result' AS result;  -- bad_duration
SELECT public.pause_end('rider', '447700900801', NULL, 'resumed') ->> 'result' AS result;                   -- resumed
SELECT public.is_paused('rider', '447700900801', NULL) AS paused;                                           -- false

-- ===== STAGE 7: the dispatch gate (read the reason column; nothing is offered: no order exists for these riders) =====
UPDATE public.rider_master SET status = 'active', is_in_shift = true WHERE rider_id = '447700900803';
SELECT public.pause_start('rider', '447700900803', NULL, '6h', 'operator', 'harness') ->> 'result' AS result;  -- paused
SELECT rider_id, status, is_in_shift, public.is_paused('rider', rider_id, NULL) AS paused,
       (status = 'active' AND is_in_shift AND NOT public.is_paused('rider', rider_id, NULL)) AS dispatchable
  FROM public.rider_master WHERE rider_id LIKE '4477009008%' ORDER BY rider_id;
-- 801: inactive -> false | 803: active but paused -> false | 804: inactive -> false
SELECT public.pause_end('rider', '447700900803', NULL, 'operator') ->> 'result' AS result;  -- resumed
UPDATE public.rider_master SET status = 'inactive', is_in_shift = false WHERE rider_id = '447700900803';

-- ===== STAGE 8: LIVE TELEGRAM with your own phone (manual; needs the R1 code deployed and @ByteloopRidersBot configured) =====
-- Before: note your row (if any) so you can restore it.
-- SELECT rider_id, status, channel, tuid, tcid, is_in_shift FROM public.rider_master WHERE rider_id = '447448440754';
-- In Telegram: open t.me/ByteloopRidersBot?start=join -> tap "Share my phone number" ->
--   your phone is in rider_master -> "You're linked, <name>"         (row: tuid/tcid set, channel = 'telegram')
--   your phone is not             -> pick a town, then a vehicle -> "Thanks, Ordelo will activate your account"
-- Send /whoami: it shows your Telegram ids and the rider row. Forwarding someone else's contact must be refused.
-- Undo (puts you back exactly on WhatsApp; no delete):
-- UPDATE public.rider_master SET tuid = NULL, tcid = NULL, t_username = NULL, t_first_name = NULL, t_linked_at = NULL,
--        phone_verified = false, channel = 'whatsapp' WHERE rider_id = '447448440754' RETURNING rider_id, channel, tuid;
-- In phases R1-R3 channel = 'telegram' changes nothing you can see: offers still go to WhatsApp until phase R4.
