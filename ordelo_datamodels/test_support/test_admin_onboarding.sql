-- =============================================================================================
-- TEST HARNESS (not a migration): exercise the restaurant-admin roster, the phone-verified Telegram link, channels and pauses
-- on the REAL database with FAKE admins, after migrations/admin_roster_p1.sql has been applied (phase P1).
-- =============================================================================================
-- Run it ONE STAGE AT A TIME in the Supabase SQL editor (each block starts with "-- ===== STAGE n ... =====").
-- Every stage can be repeated. STAGE 0 wipes the earlier fake rows first, so start there. Each stage ends with a SELECT
-- whose comments say what you should see.
--
-- WHAT IT TOUCHES (and only these rows)
--   restaurant_admin  rows whose phone starts with 4477009009 (Ofcom's drama range 07700 900xxx: never a real phone)
--   pauses            rows whose principal starts with 4477009009
--   restaurant_master the admins array of rest_ref 'STRK' (your test restaurant): fake phones are ADDED and REMOVED, nothing
--                     else in the array or the row changes. STAGE 0 removes them again. Your own number is never edited here.
--   Fake Telegram ids 999000000901..999000000999 (far above any id Telegram hands out to people today).
--   delete            STAGE 0 deletes ONLY those fake rows (the harness's own; nothing else is ever deleted).
-- It only READS everything else. It sends NO Telegram or WhatsApp message: the functions write rows, the bots are not involved
-- until STAGE 12, which is a manual test with your own phone and its own undo.
--
-- PREREQUISITES: migrations/admin_roster_p1.sql steps 1-2 applied. The check below must show 9 / true / true.
-- Regression companion: test_support/test_restaurant_notices.sql (order cards, receipts, notices) is run three times with your
-- own channels set in STAGE 12; see docs/live-order-test-harness.md "Channel matrix".
-- Offline proof of this script: tests/sql/test_admin_onboarding_script_sql.py (isolated database).
-- =============================================================================================

-- ===== PREREQUISITES CHECK (read only) =====
SELECT
    (SELECT count(*) FROM pg_proc
      WHERE proname IN ('admin_phone_digits', 'admin_recipients', 'admin_for_tuid', 't_admin_link', 't_admin_profile',
                        'admin_set_channels', 'admin_unlink_telegram', 'admin_roster_status', 't_admin_restaurants')) AS functions,       -- 9
    (SELECT to_regclass('public.restaurant_admin') IS NOT NULL)                                                             AS table_exists,    -- true
    (SELECT count(*) = 1 FROM public.restaurant_master WHERE rest_ref = 'STRK')                                             AS strk_exists;     -- true

-- ===== STAGE 0: RESET (deletes ONLY the harness's own fake rows) =====
DELETE FROM public.pauses WHERE principal LIKE '4477009009%';
DELETE FROM public.restaurant_admin WHERE phone LIKE '4477009009%' OR tuid BETWEEN 999000000901 AND 999000000999;
UPDATE public.restaurant_master
   SET admins = ARRAY(SELECT a FROM unnest(admins) WITH ORDINALITY AS t (a, o) WHERE a NOT LIKE '%4477009009%' ORDER BY o)
 WHERE rest_ref = 'STRK' AND EXISTS (SELECT 1 FROM unnest(admins) a WHERE a LIKE '%4477009009%');
SELECT (SELECT count(*) FROM public.restaurant_admin WHERE phone LIKE '4477009009%')                             AS fake_records_left,   -- 0
       (SELECT count(*) FROM public.restaurant_master, unnest(admins) a WHERE rest_ref = 'STRK' AND a LIKE '%4477009009%') AS fake_admins_left; -- 0

-- ===== STAGE 1: a phone that is on NO restaurant's list shares its number: refused, nothing written =====
SELECT public.t_admin_link(999000000901, 999000000901, '+44 7700 900901', 'harness_a', 'Harness') ->> 'result' AS result;  -- not_on_roster
SELECT count(*) AS records FROM public.restaurant_admin WHERE phone = '447700900901';  -- 0

-- ===== STAGE 2: the operator adds the phone to STRK (what the sys-admin page does): WhatsApp only, no record =====
UPDATE public.restaurant_master SET admins = array_append(admins, '447700900901') WHERE rest_ref = 'STRK' AND NOT ('447700900901' = ANY (admins));
SELECT (SELECT count(*) FROM public.admin_recipients('STRK', 'whatsapp') WHERE phone = '447700900901') AS on_whatsapp,   -- 1
       (SELECT count(*) FROM public.admin_recipients('STRK', 'telegram') WHERE phone = '447700900901') AS on_telegram,   -- 0
       (SELECT (e ->> 'linked')::boolean FROM jsonb_array_elements(public.admin_roster_status('STRK')) e WHERE e ->> 'phone' = '447700900901') AS linked; -- false

-- ===== STAGE 3: the admin shares their own number in the restaurant bot: linked, Telegram only (D6) =====
SELECT public.t_admin_link(999000000901, 999000000901, '+44 7700 900901', 'harness_a', 'Harness') AS out;
-- out.result = linked, out.channels = ["telegram"], out.restaurants includes STRK
SELECT (SELECT count(*) FROM public.admin_recipients('STRK', 'whatsapp') WHERE phone = '447700900901') AS on_whatsapp,   -- 0
       (SELECT count(*) FROM public.admin_recipients('STRK', 'telegram') WHERE phone = '447700900901') AS on_telegram,   -- 1
       (SELECT count(*) FROM public.t_alert_destinations('rest_admin', 'STRK') WHERE phone = '447700900901') AS gets_cards; -- 1

-- ===== STAGE 4: the same person runs /start again (refresh): channels kept =====
SELECT public.t_admin_link(999000000901, -100901, '447700900901', 'harness_a2', 'Harness') ->> 'result' AS result;  -- already_linked
SELECT tcid, t_username, channels FROM public.restaurant_admin WHERE phone = '447700900901';  -- -100901 | harness_a2 | {telegram}

-- ===== STAGE 5: a NEW Telegram account shares the same phone (new handset): the link moves =====
SELECT public.t_admin_link(999000000902, 999000000902, '447700900901', 'harness_b', 'Harness') AS out;
-- out.result = relinked, out.previous_tuid = 999000000901, out.previous_username = harness_a2
SELECT public.admin_for_tuid(999000000901, 'STRK') AS old_account, public.admin_for_tuid(999000000902, 'STRK') AS new_account;  -- NULL | 447700900901

-- ===== STAGE 6: that account tries ANOTHER admin's phone: refused =====
UPDATE public.restaurant_master SET admins = array_append(admins, '447700900903') WHERE rest_ref = 'STRK' AND NOT ('447700900903' = ANY (admins));
SELECT public.t_admin_link(999000000902, 999000000902, '447700900903', 'harness_b', 'Harness') AS out;  -- {"result": "tuid_taken", "phone_last4": "0901"}
SELECT count(*) AS records FROM public.restaurant_admin WHERE phone = '447700900903';  -- 0 (untouched)

-- ===== STAGE 7: channels (what /channels and the sys-admin page call) =====
SELECT public.admin_set_channels('447700900901', ARRAY['whatsapp', 'telegram'], 'harness') AS out;  -- {"result": "ok", "channels": ["telegram", "whatsapp"]}
SELECT (SELECT count(*) FROM public.admin_recipients('STRK', 'whatsapp') WHERE phone = '447700900901') AS on_whatsapp,   -- 1
       (SELECT count(*) FROM public.admin_recipients('STRK', 'telegram') WHERE phone = '447700900901') AS on_telegram;   -- 1
SELECT public.admin_set_channels('447700900901', ARRAY['whatsapp'], 'harness') ->> 'result' AS result;  -- ok
SELECT public.admin_set_channels('447700900901', ARRAY[]::text[], 'harness') ->> 'result' AS result;    -- bad_channels
SELECT public.admin_set_channels('447700900901', ARRAY['fax'], 'harness') ->> 'result' AS result;       -- bad_channels
SELECT public.admin_set_channels('447700900903', ARRAY['telegram'], 'harness') ->> 'result' AS result;  -- not_found (no record yet)
SELECT public.admin_set_channels('447700900901', ARRAY['telegram'], 'harness') ->> 'result' AS result;  -- ok (back to Telegram only)

-- ===== STAGE 8: a pause covers EVERY channel (the last-admin guard is proven offline; your own number is not touched here) =====
SELECT public.admin_set_channels('447700900901', ARRAY['whatsapp', 'telegram'], 'harness') ->> 'result' AS result;  -- ok
SELECT public.pause_start('rest_admin', '447700900901', 'STRK', '6h', 'operator', 'harness') ->> 'result' AS result;  -- paused
SELECT (SELECT count(*) FROM public.admin_recipients('STRK', 'whatsapp') WHERE phone = '447700900901') AS on_whatsapp,   -- 0
       (SELECT count(*) FROM public.admin_recipients('STRK', 'telegram') WHERE phone = '447700900901') AS on_telegram,   -- 0
       (SELECT count(*) FROM public.t_order_card_destinations('rest_admin', 'STRK') WHERE phone = '447700900901') AS can_still_tap; -- 1
SELECT public.pause_end('rest_admin', '447700900901', 'STRK', 'operator') ->> 'result' AS result;  -- resumed
SELECT (SELECT count(*) FROM public.admin_recipients('STRK', 'whatsapp') WHERE phone = '447700900901') AS on_whatsapp,   -- 1
       (SELECT count(*) FROM public.admin_recipients('STRK', 'telegram') WHERE phone = '447700900901') AS on_telegram;   -- 1

-- ===== STAGE 9: the operator removes the phone from the list: no authority, no messages, record kept =====
UPDATE public.restaurant_master SET admins = array_remove(admins, '447700900901') WHERE rest_ref = 'STRK';
SELECT public.t_admin_profile(999000000902) ->> 'result' AS result,  -- not_on_roster
       public.admin_for_tuid(999000000902, 'STRK') AS phone,         -- NULL
       (SELECT count(*) FROM public.restaurant_admin WHERE phone = '447700900901') AS record_kept;  -- 1
UPDATE public.restaurant_master SET admins = array_append(admins, '447700900901') WHERE rest_ref = 'STRK' AND NOT ('447700900901' = ANY (admins));
SELECT public.t_admin_profile(999000000902) ->> 'result' AS result,  -- ok (back, no re-link needed)
       public.admin_for_tuid(999000000902, 'STRK') AS phone;         -- 447700900901

-- ===== STAGE 10: the operator unlinks Telegram: back to WhatsApp only =====
SELECT public.admin_unlink_telegram('447700900901', 'harness') ->> 'result' AS result;  -- ok
SELECT channels, tuid FROM public.restaurant_admin WHERE phone = '447700900901';  -- {whatsapp} | NULL
SELECT public.admin_unlink_telegram('447700900901', 'harness') ->> 'result' AS result;  -- not_linked

-- ===== STAGE 11: TRANSITION check (read only, P1/P2 only): an admin with an old claimed invite and NO record keeps Telegram =====
SELECT d.phone, d.label, (ra.phone IS NULL) AS invite_only
  FROM public.t_order_card_destinations('rest_admin', 'STRK') d
  LEFT JOIN public.restaurant_admin ra ON ra.phone = d.phone;
-- Your own number (if you still have a claimed STRK invite) shows invite_only = true until you link in STAGE 12; afterwards false.

-- ===== STAGE 12: LIVE TELEGRAM with your own phone (manual; needs the P1 code deployed and the restaurant bot menu republished) =====
-- Before: note your row (if any) so you can restore it.
-- SELECT * FROM public.restaurant_admin WHERE phone = '447448440754';
-- In Telegram: open t.me/OrdeloRestaurantBot?start=admin -> tap "Share my phone number" ->
--   your phone is on STRK's list   -> "You're linked" + the restaurants (row: tuid/tcid set, channels = {telegram})
--   your phone is on no list       -> a friendly refusal, and an ops line to the Ops chat
-- Forwarding someone else's contact must be refused. /whoami shows your Telegram ids and your admin record; /channels changes where
-- you hear from Ordelo. Channel matrix for test_restaurant_notices.sql (run its stages 0-10 once per line):
-- SELECT public.admin_set_channels('447448440754', ARRAY['whatsapp'], 'owner-test');              -- WhatsApp only (like before)
-- SELECT public.admin_set_channels('447448440754', ARRAY['telegram'], 'owner-test');              -- Telegram only (P2: WhatsApp silent)
-- SELECT public.admin_set_channels('447448440754', ARRAY['whatsapp', 'telegram'], 'owner-test');  -- both
-- Undo (puts you back exactly on WhatsApp; no delete):
-- SELECT public.admin_unlink_telegram('447448440754', 'owner-test');
