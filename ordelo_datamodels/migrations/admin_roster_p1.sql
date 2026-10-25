-- MIGRATION (history; do not edit the statements below)
-- Applied to live: 2026-10-25 (owner; t_order_alerts.sql was re-run once because the destinations were still the old bodies). Written for plans/restaurant-admin-roster-onboarding-plan.md, phase P1; the owner applies it.
-- Current definitions now live in: restaurant_admin/admin_roster.sql, restaurant_admin/restaurant_order_decision.sql,
--   telegram/t_order_alerts.sql, telegram/t_admin_pauses.sql
-- Purpose: restaurant-admin roster and phone-verified Telegram link (P1). Adds restaurant_admin / admin_roster and the t_admin_*
--          functions; the Telegram destination functions read the roster and keep reading claimed invites for admins who have no
--          record yet (TRANSITION), so nothing changes for anyone until an admin links. WhatsApp is not touched in P1.
-- The feature files above are the current truth; this file only records the one-off change.

/*
HOW TO APPLY (Supabase SQL editor, one block at a time; no BEGIN/COMMIT):
  STEP 0  PRE-CHECKs below; fix PRE-CHECK 1 rows in the sys-admin page first (they would drop off the roster).
  STEP 1  Apply whole files, in this order:
            ordelo_datamodels/restaurant_admin/admin_roster.sql
            ordelo_datamodels/restaurant_admin/restaurant_order_decision.sql   (t_order_admin_phone, restaurant_admin_label)
            ordelo_datamodels/telegram/t_order_alerts.sql                      (re-schedules job_t_order_alerts unchanged)
            ordelo_datamodels/telegram/t_admin_pauses.sql                      (t_admin_restaurants, new)
  STEP 2  VERIFY below. Do NOT live-test until destinations_use_roster = true: if it is false, t_order_alerts.sql did not apply,
          so linked admins get no Telegram alerts once their old invite is revoked. Also check t_alert_destinations contains 'restaurant_admin'.
  STEP 3  Deploy the P1 code (OrdeloAgent + restaurant-frontend), then python scripts/datamodels/drift_check.py
  STEP 4  Re-publish the restaurant bot menu: notebooks/telegram/tgram_setup_bot.py with BOT_KEY = 'rest_admin'
          (/start text changed, /channels added).
  STEP 5  OPTIONAL (owner decision): stop pending invites from being claimed by an old message:
            UPDATE public.t_invites SET status = 'revoked' WHERE status = 'pending' RETURNING invite_code, rest_ref;
  STEP 6  Live test: test_support/test_admin_onboarding.sql, then test_support/test_restaurant_notices.sql (section 9).
  Order: STEP 1 before the deploy (the new code calls t_admin_link / t_admin_profile; old code ignores the new objects,
  and the new t_* bodies give exactly today's destinations while no admin record exists: proven by VERIFY 2).
ROLLBACK: redeploy the previous code; re-apply the previous t_order_alerts.sql, restaurant_order_decision.sql and
  t_admin_pauses.sql from git (git show d486b43:<path>). The new table and functions are additive; leave them.
*/

-- PRE-CHECK 1: admins[] entries the roster would reject (must be 0 rows, or fix them first in the sys-admin page)
SELECT rm.rest_ref, a AS entry FROM public.restaurant_master rm, unnest(coalesce(rm.admins, '{}')) a
 WHERE regexp_replace(a, '\D', '', 'g') !~ '^[0-9]{8,15}$';

-- PRE-CHECK 2: today's Telegram destinations per restaurant (compare with VERIFY 2)
SELECT rest_ref, (SELECT count(*) FROM public.t_order_card_destinations('rest_admin', rest_ref)) AS destinations
  FROM public.restaurant_master ORDER BY 1;

-- PRE-CHECK 3: phones on more than one restaurant (expected: your team's numbers; allowed)
SELECT regexp_replace(a, '\D', '', 'g') AS phone, array_agg(rest_ref ORDER BY rest_ref) AS restaurants
  FROM public.restaurant_master, unnest(coalesce(admins, '{}')) a GROUP BY 1 HAVING count(*) > 1;

-- STEP 1 is "apply the four whole files listed above"; there are no statements of its own in this file.

-- STEP 5 (OPTIONAL, owner decision): stop pending invites from being claimed by an old message. No delete.
-- UPDATE public.t_invites SET status = 'revoked' WHERE status = 'pending' RETURNING invite_code, rest_ref;

-- VERIFY (after STEP 1): 9 / 0 / true
SELECT
  (SELECT count(*) FROM pg_proc WHERE proname IN ('admin_phone_digits','admin_recipients','admin_for_tuid','t_admin_link',
      't_admin_profile','admin_set_channels','admin_unlink_telegram','admin_roster_status','t_admin_restaurants')) AS functions,
  (SELECT count(*) FROM public.restaurant_admin) AS admin_records,
  (SELECT prosrc LIKE '%admin_roster%' FROM pg_proc WHERE proname = 't_order_card_destinations') AS destinations_use_roster;

-- VERIFY 2: same numbers as PRE-CHECK 2 (no admin record exists yet, so nothing may change)
SELECT rest_ref, (SELECT count(*) FROM public.t_order_card_destinations('rest_admin', rest_ref)) AS destinations
  FROM public.restaurant_master ORDER BY 1;

-- COMMENT ON COLUMN (owner step, cosmetic): the admins column is now the authoritative list; links live in restaurant_admin.
-- COMMENT ON COLUMN public.restaurant_master.admins IS 'Authoritative admin list (phones). Telegram link and channels per phone: restaurant_admin / admin_roster.';
