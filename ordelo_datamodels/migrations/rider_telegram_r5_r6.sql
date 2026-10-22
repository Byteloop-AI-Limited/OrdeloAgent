-- MIGRATION (history; do not edit the statements below)
-- Applied to live: Steps 1-3 verified on 2026-10-22 (VERIFY true / 7 / true / true / 4 / 0 after the owner applied
--   restaurant_ready_adjust_notices.sql). Code and both command menus deployed per owner. Step 6 done: job_pause_sweep
--   is scheduled (owner, 2026-10-23); live tests and drift_check passed.
-- Current definitions now live in: rider_location/wa_location.sql, availability/pauses.sql, availability/rider_shift.sql,
--   dispatch/enquire_shift_availability.sql, telegram/t_order_alerts.sql, restaurant_admin/restaurant_ready_adjust_notices.sql,
--   telegram/t_admin_pauses.sql, availability/job_pause_sweep.sql
-- Purpose: Telegram rider bot R5-R6 (plans/telegram-rider-bot-plan.md). R5: Telegram location replies are stored as
--          'telegram_current'; riders' shift start/end goes through one RPC with the status gate; only WhatsApp riders get the
--          daily shift question; Telegram riders are switched on once; the pause sweep is scheduled. R6: restaurant admins can
--          pause their Telegram alerts (last-admin guard), and new cards, receipts and notices skip paused admins.
-- The feature files above are the current truth; this file only records the one-off change.

/*
HOW TO APPLY (Supabase SQL editor, one block at a time, in this order; no BEGIN/COMMIT):

  Already done (2026-10-22): migrations/rider_telegram_r1.sql steps 0-6 and migrations/rider_telegram_r2_r4.sql steps 0-4.

  STEP 0  Run the four PRE-CHECK queries below and read the results.
  STEP 1  Run the wa_location_observation ALTERs in this file (safe to re-run).
  STEP 2  Run the UPDATE in this file: every Telegram rider in shift (D53: Telegram riders are on by default; PRE-CHECK 2 lists
          who changes). Status still gates dispatch: an 'inactive' rider stays out whatever is_in_shift says.
  STEP 3  Apply these whole files, in this order:
            ordelo_datamodels/availability/pauses.sql                          (pause_options(), the last-admin guard)
            ordelo_datamodels/availability/rider_shift.sql                     (rider_set_shift(), new)
            ordelo_datamodels/dispatch/enquire_shift_availability.sql          (WhatsApp riders only; re-schedules the 11:00 job
                                                                                unchanged)
            ordelo_datamodels/telegram/t_order_alerts.sql                      (t_alert_destinations(), new; re-schedules
                                                                                job_t_order_alerts unchanged)
            ordelo_datamodels/restaurant_admin/restaurant_ready_adjust_notices.sql (receipts and notices skip paused admins;
                                                                                re-schedules job_t_receipt_refresh unchanged)
            ordelo_datamodels/telegram/t_admin_pauses.sql                      (t_admin_pause*, new)
  STEP 4  Run the VERIFY query at the bottom: true / 7 / true / true / 4 / 0.
  STEP 5  Deploy the R5-R6 code, then  python scripts/datamodels/drift_check.py
  STEP 6  Apply the whole file  ordelo_datamodels/availability/job_pause_sweep.sql  (creates the pg_cron job 'job_pause_sweep',
          every minute) and run VERIFY 2: 1.
  STEP 7  Re-publish both command menus (notebooks/telegram/tgram_setup_bot.py): BOT_KEY = 'rider' (adds /shift, /off, /on) and
          BOT_KEY = 'rest_admin' (adds /off, /on). The webhooks need no change (a shared location is a 'message' update).
  STEP 8  Live test: ordelo_datamodels/test_support/test_rider_pauses_and_locations.sql.

  Order matters: apply steps 1-3 BEFORE deploying. The new code calls rider_set_shift() for every WhatsApp shift answer and
  stores 'telegram_current' locations; the old code ignores everything this migration adds, so applying early is harmless.
  Step 6 comes AFTER the deploy because the job POSTs to /pause-hooks/sweep, which only the new code has (applying it early is
  harmless too while nobody is paused, but a pause created by an operator would then be POSTed to a 404 every minute).

ROLLBACK (only if needed; each line stands alone):
  Redeploy the previous code first. Then, optionally:
  SELECT cron.unschedule('job_pause_sweep');                    (no more ends-soon / back-on messages; pauses still end on time)
  The new functions are additive. To give Telegram riders the shift question again, re-apply the previous
  enquire_shift_availability() (git history) - not recommended: Telegram riders are on by default.
*/

-- ===== PRE-CHECK 1: R1-R4 are in place (must return true, true, true) =====
SELECT
    EXISTS (
        SELECT
            1
        FROM
            pg_proc
        WHERE
            proname = 'rider_thread_open') AS r2_r4_thread_functions,
    EXISTS (
        SELECT
            1
        FROM
            information_schema.tables
        WHERE
            table_schema = 'public'
            AND table_name = 'pauses') AS r1_pauses_table,
    EXISTS (
        SELECT
            1
        FROM
            information_schema.columns
        WHERE
            table_schema = 'public'
            AND table_name = 'delivery_dispatch'
            AND column_name = 'channel') AS r2_r4_dispatch_channel;

-- ===== PRE-CHECK 2: Telegram riders and their shift flag (STEP 2 sets is_in_shift = true for the 'false' rows) =====
SELECT
    rider_id,
    rider_name,
    status,
    is_in_shift
FROM
    public.rider_master
WHERE
    channel = 'telegram'
ORDER BY
    is_in_shift,
    rider_id;

-- ===== PRE-CHECK 3: restaurant admins (informational: with one admin, that admin can never pause - the last-admin guard) =====
SELECT
    rest_ref,
    rest_name,
    coalesce(cardinality(admins), 0) AS admin_count
FROM
    public.restaurant_master
ORDER BY
    admin_count,
    rest_ref;

-- ===== PRE-CHECK 4: location sources stored so far (informational: only whatsapp_current / restaurant_confirmation) =====
SELECT
    source,
    count(*)
FROM
    public.wa_location_observation
GROUP BY
    source
ORDER BY
    source;

-- ===== STEP 1: wa_location_observation accepts 'telegram_current' (each statement stands alone; safe to re-run) =====
ALTER TABLE public.wa_location_observation
    DROP CONSTRAINT IF EXISTS wa_location_observation_source_check;

ALTER TABLE public.wa_location_observation
    ADD CONSTRAINT wa_location_observation_source_check CHECK (((source)::text = ANY ((ARRAY['whatsapp_current'::character varying, 'telegram_current'::character varying, 'restaurant_confirmation'::character varying])::text[])));

-- ===== STEP 2: Telegram riders in shift (D53; safe to re-run: a second run changes nothing) =====
UPDATE
    public.rider_master
SET
    is_in_shift = TRUE
WHERE
    channel = 'telegram'
    AND is_in_shift IS NOT TRUE
RETURNING
    rider_id,
    rider_name,
    status;

-- ===== VERIFY (after step 3) =====
SELECT
    (
        SELECT
            pg_get_constraintdef(oid) LIKE '%telegram_current%'
        FROM
            pg_constraint
        WHERE
            conname = 'wa_location_observation_source_check') AS telegram_location_source, -- true
    (
        SELECT
            count(*)
        FROM
            pg_proc
        WHERE
            proname IN ('pause_options', 'rider_set_shift', 't_alert_destinations', 't_admin_pause', 't_admin_resume', 't_admin_pause_status', 't_admin_pause_chats')) AS new_functions, -- 7
    (
        SELECT
            prosrc LIKE '%channel = ''whatsapp''%'
        FROM
            pg_proc
        WHERE
            proname = 'enquire_shift_availability') AS shift_question_whatsapp_only, -- true
    (
        SELECT
            prosrc LIKE '%not_allowed%'
        FROM
            pg_proc
        WHERE
            proname = 'pause_start') AS last_admin_guard, -- true
    (
        SELECT
            count(*)
        FROM
            pg_proc
        WHERE
            proname IN ('t_order_card_snapshot', 't_receipt_snapshot', 't_notice_targets', 'job_t_order_alerts')
            AND prosrc LIKE '%t_alert_destinations%') AS senders_skip_paused_admins, -- 4
    (
        SELECT
            count(*)
        FROM
            public.rider_master
        WHERE
            channel = 'telegram'
            AND is_in_shift IS NOT TRUE) AS telegram_riders_off_shift; -- 0

-- ===== VERIFY 2 (after step 6) =====
SELECT
    count(*) AS pause_sweep_job -- 1
FROM
    cron.job
WHERE
    jobname = 'job_pause_sweep';
