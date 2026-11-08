-- =====================================================================================
-- How to onboard a restaurant admin onto the Telegram restaurant-admin bot
-- =====================================================================================
-- Admins link by SHARING THEIR PHONE in the bot (verified contact share), not by invite link.
-- restaurant_master.admins is the ONLY authority on who may link; the restaurant_admin table
-- just records each phone's Telegram link and channels. All roster RPCs are service-role only.
--
-- Full docs: docs/telegram-layer.md  -> "Admin roster" (operator SOP + re-testing)
--            .claude/skills/database-operations/SKILL.md -> "Restaurant-admin roster"
--            plans/restaurant-admin-roster-onboarding-plan.md
-- =====================================================================================

select admins,* from restaurant_master where rest_ref='STRK';
update restaurant_master set admins=Array['447448440754','447929843965','447446933210'] where rest_ref='STRK';

select * from restaurant_admin where phone='447448440754';
-- -------------------------------------------------------------------------------------
-- STEP 0 — the bot link (same for every admin, NOT a secret)
-- -------------------------------------------------------------------------------------
-- Live bot:  https://t.me/OrdeloRestaurantBot?start=admin
-- The link is built from ordelo_config.TGRAM_REST_ADMIN_BOT_USERNAME. Read the real value
-- (copy it from the sys-admin page if the bot ever changes):
SELECT 'https://t.me/' || config_value || '?start=admin' AS bot_link
FROM ordelo_config
WHERE config_key = 'TGRAM_REST_ADMIN_BOT_USERNAME';


-- -------------------------------------------------------------------------------------
-- STEP 1 — put the admin's phone on the restaurant's roster
-- -------------------------------------------------------------------------------------
-- admins is text[] of digits-only phone numbers (no '+'). Normally done in the sys-admin
-- page (app/sys-admin/restaurants/[rest_ref]/admins); SQL equivalent, idempotent:
UPDATE restaurant_master
SET admins = array_append(admins, '447448440754')
WHERE rest_ref = 'ELAS';


-- -------------------------------------------------------------------------------------
-- STEP 2 — send the admin the STEP 0 link. In a PRIVATE chat they:
--   /start -> tap "Share my phone number"  (accepted only when contact.user_id == sender;
--   typed or forwarded numbers are refused)
-- t_admin_link() then decides:
--   linked          first link for this phone; channels := {telegram} (WhatsApp stops)
--   relinked        same phone, new Telegram account - link moves, ops is told
--   already_linked  same account again - nothing reset
--   not_on_roster   phone on no restaurant's admins list - refused, ops is told
--   tuid_taken      that Telegram account is linked to another phone - refused, ops told
--   bad_phone       not a usable mobile number
-- -------------------------------------------------------------------------------------


-- -------------------------------------------------------------------------------------
-- STEP 3 — verify
-- -------------------------------------------------------------------------------------
-- Every roster phone for a restaurant: link state + channels (what the sys-admin page shows):
SELECT admin_roster_status('ELAS');

-- One phone's admin record:
SELECT phone, channels, channels_set_by, tuid, tcid, t_username, t_first_name, t_linked_at
FROM restaurant_admin
WHERE phone = '447700900123';


-- -------------------------------------------------------------------------------------
-- UNLINK a number (reset Telegram onboarding so it can be re-tested)
-- -------------------------------------------------------------------------------------
-- Clears tuid, tcid, t_username, t_first_name, t_linked_at and sets channels back to
-- {whatsapp}. The sys-admin "Unlink Telegram" button calls this same RPC.
-- Returns {result: ok | not_found | not_linked}  (not_found = no restaurant_admin row).
-- After this, /start -> share phone runs the full onboarding again and returns 'linked'.
-- NOTE: same phone + same Telegram account WITHOUT unlinking returns 'already_linked'.
SELECT admin_unlink_telegram('447448440754', 'test');

-- Do NOT delete the restaurant_admin row - unlink is enough, and deletes need approval.

SELECT count(*) AS still_linked
FROM restaurant_admin
WHERE phone = '447448440754' AND tuid IS NOT NULL;


-- -------------------------------------------------------------------------------------
-- OPTIONAL — change an admin's channels by hand (whatsapp, telegram or both, never none)
-- -------------------------------------------------------------------------------------
-- SELECT admin_set_channels('447700900123', ARRAY['telegram','whatsapp'], 'operator-name');
-- -- {result: ok | not_found | bad_channels | not_linked}


-- -------------------------------------------------------------------------------------
-- OPTIONAL — remove an admin entirely (the real off switch)
-- -------------------------------------------------------------------------------------
-- Unlinking only cuts Telegram; the phone is still an admin on WhatsApp. To take them off
-- the restaurant completely, remove the phone from the admins list:
-- UPDATE restaurant_master
-- SET admins = array_remove(admins, '447700900123')
-- WHERE rest_ref = 'ELAS';

-- -------------------------------------------------------------------------------------
-- Replay rider onboarding
-- -------------------------------------------------------------------------------------
select rider_id, tuid, channel from rider_master where rider_id='447448440754';
select * from delivery_inflight;

UPDATE public.rider_master AS r
SET tuid = NULL,
    tcid = NULL,
    t_username = NULL,
    t_first_name = NULL,
    t_linked_at = NULL,
    phone_verified = FALSE,
    channel = 'whatsapp',
    is_in_shift = FALSE
WHERE r.rider_id = '447448440754'
  AND r.tuid = 7279908526
  AND NOT EXISTS (
      SELECT 1
      FROM public.delivery_inflight AS d
      WHERE d.rider_id = r.rider_id
  )
RETURNING r.rider_id, r.channel, r.is_in_shift,
          r.tuid IS NOT NULL AS telegram_linked;

