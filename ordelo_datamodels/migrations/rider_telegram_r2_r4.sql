-- MIGRATION (history; do not edit the statements below)
-- Applied to live: Applied by the owner on 2026-10-22 (steps 0-4, VERIFY 3/1/6/0); code deployed and a rider job tested live on Telegram and WhatsApp.
-- Current definitions now live in: dispatch/delivery_dispatch.sql, agent_threads/rider_threads.sql
-- Purpose: Telegram rider bot R2-R4: delivery_dispatch gets the offer's channel (fixed per dispatch), the offer message ref and
--          the rider thread id; the rider thread functions (one thread per assigned dispatch). The shared thread table is unchanged.
-- The feature files above are the current truth; this file only records the one-off change.

/*
HOW TO APPLY (Supabase SQL editor, one block at a time, in this order; no BEGIN/COMMIT):

  Already done (2026-10-22): migrations/rider_telegram_r1.sql steps 0-6.

  STEP 0  Run the two PRE-CHECK queries below and read the results.
  STEP 1  Run the ALTER statements in this file (safe to re-run).
  STEP 2  Apply the whole file  ordelo_datamodels/dispatch/delivery_dispatch.sql
          (adds the channel-stamping row trigger; the existing statement trigger trigger_delivery_dispatch_whook is re-created
           unchanged; CREATE TABLE IF NOT EXISTS is a no-op on the live table)
  STEP 3  Apply the whole file  ordelo_datamodels/agent_threads/rider_threads.sql   (six rider_thread_* functions)
  STEP 4  Run the VERIFY query at the bottom: 3 / 1 / 6 / 0.
  STEP 5  Deploy the code (it calls rider_thread_* and writes delivery_dispatch.channel_msg_ref), then
          python scripts/datamodels/drift_check.py
  STEP 6  Live smoke test: ordelo_datamodels/test_support/test_rider_telegram_jobs.sql (with test_restaurant_notices.sql).

  Order matters: apply steps 1-3 BEFORE deploying. The old code ignores the new columns and functions, so applying early is
  harmless; the new code without them fails at the first assignment (rider_thread_open does not exist).
  Threads that are open when you deploy (ids 'ORDELO-<uuid>') keep working: rider_thread_active() finds them, and they close
  the old way. PRE-CHECK 2 shows how many there are.

  Do NOT apply availability/job_pause_sweep.sql yet (phase R5).

ROLLBACK (only if needed; each line stands alone):
  Redeploy the previous code first. Then, optionally:
  DROP TRIGGER IF EXISTS trigger_delivery_dispatch_stamp_channel ON public.delivery_dispatch;   (offers then default to whatsapp)
  The new columns and functions are additive; leaving them is harmless with the previous code.
*/

-- ===== PRE-CHECK 1: R1 is in place (must return true, true) =====
SELECT
    EXISTS (
        SELECT
            1
        FROM
            information_schema.columns
        WHERE
            table_schema = 'public'
            AND table_name = 'rider_master'
            AND column_name = 'channel') AS rider_channel_column,
    EXISTS (
        SELECT
            1
        FROM
            pg_proc
        WHERE
            proname = 't_rider_link') AS onboarding_functions;

-- ===== PRE-CHECK 2: rider threads open right now (informational; they keep working after the deploy) =====
SELECT
    thread_id,
    recipient,
    last_access_dtts
FROM
    public.thread
WHERE
    agent = 'ORDELO'
    AND is_active IS TRUE
ORDER BY
    last_access_dtts DESC;

-- ===== STEP 1: the one-off ALTERs (each statement stands alone; safe to re-run) =====
-- Existing rows get channel 'whatsapp' (that is how every existing offer was sent).
ALTER TABLE public.delivery_dispatch
    ADD COLUMN IF NOT EXISTS channel text NOT NULL DEFAULT 'whatsapp'::text;

ALTER TABLE public.delivery_dispatch
    ADD COLUMN IF NOT EXISTS channel_msg_ref text;

ALTER TABLE public.delivery_dispatch
    ADD COLUMN IF NOT EXISTS thread_id text;

ALTER TABLE public.delivery_dispatch
    DROP CONSTRAINT IF EXISTS delivery_dispatch_channel_check;

ALTER TABLE public.delivery_dispatch
    ADD CONSTRAINT delivery_dispatch_channel_check CHECK ((channel = ANY (ARRAY['whatsapp'::text, 'telegram'::text])));

CREATE INDEX IF NOT EXISTS delivery_dispatch_thread_id_idx ON public.delivery_dispatch USING btree (thread_id)
WHERE (thread_id IS NOT NULL);

-- ===== VERIFY (after step 3) =====
SELECT
    (
        SELECT
            count(*)
        FROM
            information_schema.columns
        WHERE
            table_schema = 'public'
            AND table_name = 'delivery_dispatch'
            AND column_name IN ('channel', 'channel_msg_ref', 'thread_id')) AS dispatch_columns, -- 3
    (
        SELECT
            count(*)
        FROM
            pg_trigger
        WHERE
            tgname = 'trigger_delivery_dispatch_stamp_channel') AS stamp_trigger, -- 1
    (
        SELECT
            count(*)
        FROM
            pg_proc
        WHERE
            proname IN ('rider_thread_id', 'rider_thread_open', 'rider_thread_touch', 'rider_thread_active', 'rider_thread_describe', 'rider_thread_close')) AS thread_functions, -- 6
    (
        SELECT
            count(*)
        FROM
            public.delivery_dispatch
        WHERE
            channel IS DISTINCT FROM 'whatsapp') AS non_whatsapp_dispatches; -- 0 until a Telegram rider gets an offer
