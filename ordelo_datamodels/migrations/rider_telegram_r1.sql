-- MIGRATION (history; do not edit the statements below)
-- Applied to live: NOT applied yet (phase R1 of plans/telegram-rider-bot-plan.md; the owner runs it).
-- Current definitions now live in: core/rider_master.sql, telegram/t_rider_onboarding.sql, availability/pauses.sql, dispatch/job_create_dispatch.sql
-- Purpose: Rider Telegram onboarding (R1): rider_master gets a unique rider_id, channel and the Telegram link columns.
-- The feature files above are the current truth; this file only records the one-off change.

/*
HOW TO APPLY (Supabase SQL editor, one block at a time, in this order; no BEGIN/COMMIT):

  STEP 0  Run the three PRE-CHECK queries below and read the results. Fix anything they list BEFORE step 1.
  STEP 1  Run the ALTER statements in this file (safe to re-run).
  STEP 2  Apply the whole file  ordelo_datamodels/core/rider_master.sql        (comments only; the table already exists)
  STEP 3  Apply the whole file  ordelo_datamodels/availability/pauses.sql      (table pauses, is_paused(), config rows)
  STEP 4  Apply the whole file  ordelo_datamodels/telegram/t_rider_onboarding.sql
  STEP 5  Apply the whole file  ordelo_datamodels/dispatch/job_create_dispatch.sql
          (get_available_riders gains status = 'active' AND NOT is_paused(...); job_create_dispatch is unchanged;
           the file's cron.schedule re-saves the existing 'job_create_dispatch' job in place)
  STEP 6  Run the VERIFY query at the bottom.
  STEP 7  Optional live smoke test: ordelo_datamodels/test_support/test_rider_onboarding.sql
  Then:   python scripts/datamodels/drift_check.py

  Do NOT apply availability/job_pause_sweep.sql yet (phase R5).

ROLLBACK (only if needed; each line stands alone):
  CREATE OR REPLACE get_available_riders from git history (the pre-R1 body has no status / is_paused conditions).
  The new columns are additive and unused by WhatsApp code; leaving them is harmless.
*/

-- ===== PRE-CHECK 1: rider_id duplicates (must return 0 rows; merge or fix them first) =====
SELECT
    rider_id,
    count(*) AS n,
    array_agg(id ORDER BY id) AS ids,
    array_agg(rider_name ORDER BY id) AS names
FROM
    public.rider_master
GROUP BY
    rider_id
HAVING
    count(*) > 1;

-- ===== PRE-CHECK 2: rider_id NULL or not 8-12 digits (must return 0 rows) =====
SELECT
    id,
    rider_id,
    rider_name,
    status
FROM
    public.rider_master
WHERE
    rider_id IS NULL
    OR rider_id !~ '^[0-9]{8,12}$';

-- ===== PRE-CHECK 3: status values. After step 5 ONLY 'active' (exact spelling) is dispatchable. =====
-- If you see 'Active', 'ACTIVE ' etc. for riders who should keep getting jobs, fix them first, e.g.
--   UPDATE public.rider_master SET status = 'active' WHERE status = 'Active' RETURNING id, rider_id, status;
SELECT
    status,
    count(*) AS riders,
    count(*) FILTER (WHERE is_in_shift) AS in_shift_now
FROM
    public.rider_master
GROUP BY
    status
ORDER BY
    status;

-- ===== STEP 1: the one-off ALTERs (each statement stands alone; safe to re-run) =====
ALTER TABLE public.rider_master
    ALTER COLUMN rider_id SET NOT NULL;

ALTER TABLE public.rider_master
    ADD COLUMN IF NOT EXISTS channel text NOT NULL DEFAULT 'whatsapp'::text;

ALTER TABLE public.rider_master
    ADD COLUMN IF NOT EXISTS tuid bigint;

ALTER TABLE public.rider_master
    ADD COLUMN IF NOT EXISTS tcid bigint;

ALTER TABLE public.rider_master
    ADD COLUMN IF NOT EXISTS t_username text;

ALTER TABLE public.rider_master
    ADD COLUMN IF NOT EXISTS t_first_name text;

ALTER TABLE public.rider_master
    ADD COLUMN IF NOT EXISTS t_linked_at timestamp with time zone;

ALTER TABLE public.rider_master
    ADD COLUMN IF NOT EXISTS phone_verified boolean NOT NULL DEFAULT FALSE;

ALTER TABLE public.rider_master
    DROP CONSTRAINT IF EXISTS rider_master_rider_id_key;

ALTER TABLE public.rider_master
    ADD CONSTRAINT rider_master_rider_id_key UNIQUE (rider_id);

ALTER TABLE public.rider_master
    DROP CONSTRAINT IF EXISTS rider_master_channel_check;

ALTER TABLE public.rider_master
    ADD CONSTRAINT rider_master_channel_check CHECK ((channel = ANY (ARRAY['whatsapp'::text, 'telegram'::text])));

ALTER TABLE public.rider_master
    DROP CONSTRAINT IF EXISTS rider_master_tg_link_complete;

ALTER TABLE public.rider_master
    ADD CONSTRAINT rider_master_tg_link_complete CHECK (((tuid IS NULL) = (tcid IS NULL)));

CREATE UNIQUE INDEX IF NOT EXISTS rider_master_tuid_uidx ON public.rider_master USING btree (tuid)
WHERE (tuid IS NOT NULL);

-- ===== VERIFY (after step 5) =====
SELECT
    (
        SELECT
            count(*)
        FROM
            information_schema.columns
        WHERE
            table_schema = 'public'
            AND table_name = 'rider_master'
            AND column_name IN ('channel', 'tuid', 'tcid', 't_username', 't_first_name', 't_linked_at', 'phone_verified')) AS new_columns, -- 7
    (
        SELECT
            count(*)
        FROM
            pg_proc
        WHERE
            proname IN ('t_rider_link', 't_rider_set_profile', 't_rider_choices', 't_rider_profile', 't_rider_phone_digits', 'is_paused', 'pause_start', 'pause_end', 'pause_current', 'pause_duration')) AS functions, -- 10
    (
        SELECT
            prosrc LIKE '%is_paused%'
            AND prosrc LIKE '%status = ''active''%'
        FROM
            pg_proc
        WHERE
            proname = 'get_available_riders') AS dispatch_gate, -- true
    (
        SELECT
            count(*)
        FROM
            public.rider_master
        WHERE
            status = 'active') AS dispatchable_riders, -- same as before for riders with status 'active'
    public.t_rider_choices () AS signup_choices; -- the towns and vehicles a Telegram sign-up will see
