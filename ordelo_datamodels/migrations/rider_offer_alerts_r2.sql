-- MIGRATION (history; do not edit the statements below)
-- Applied to live: 2026-10-27 (owner-confirmed).
-- Current definitions now live in: dispatch/rider_offer_alert.sql (table, indexes), dispatch/job_rider_offer_alerts.sql (job)
-- Purpose: rider offer reminders r2 (plans/rider-dispatch-alerts-plan.md, section 11).
--          (1) Restart on Decline: when another offer of the same order is declined, every still-open Telegram offer of that
--              order starts its reminders again from "reminder 1 of 7" (now +10 ... +120 s). Each later decline restarts again.
--          (2) One overwatch escalation per dispatch ROUND (the first dispatch, and each re-offer after a cancel before pickup,
--              delivery_summary.redispatch_dtts), instead of one per order. A decline does not move a round's escalation.
--          No dispatch logic changes: job_create_dispatch, job_assign_dispatch, process_delivery and
--          dispatch_cancel_before_pickup are not touched.
-- Requires: migrations/rider_offer_alerts.sql applied (2026-10-27).

/*
HOW TO APPLY (Supabase SQL editor, one block at a time, in this order; no BEGIN/COMMIT):

  STEP 0  PRE-CHECK (read only): r1 is in place; the new columns are not there yet (false / false on a first run).
  STEP 1  COLUMNS + BACKFILL + INDEXES (safe to re-run).
  STEP 2  The new job_rider_offer_alerts() (CREATE OR REPLACE; safe to re-run). The cron job keeps running the whole time;
          its next run uses the new body. Nothing to reschedule.
  STEP 3  VERIFY: true / true / 2 / 0 / 0.
  STEP 4  Deploy the code (escalation text "after re-dispatch"; the route accepts `redispatched`). Order does not matter:
          old code ignores the extra `redispatched` key, new code defaults it to false.
  STEP 5  python scripts/datamodels/drift_check.py
  STEP 6  Live test: test_restaurant_notices.sql STAGE 2c steps f and g.

  The cron job job_rider_offer_alerts is ALREADY scheduled (r1). Do not schedule it again.

ROLLBACK (only if needed):
  Do not restore the r1 job body alone: its ON CONFLICT clauses require the r1 indexes, which r2 drops. Existing r2
  cycles and rounds can violate those old unique indexes. For a reversible operational stop, set
  RIDER_OFFER_ALERT_OFFSETS_SECS to blank; the next sweep cancels pending checkpoints. A full r1 rollback needs a
  separately reviewed data/index migration; do not delete ledger rows or recreate the old indexes blindly.
*/

-- ===== STEP 0: PRE-CHECK (read only) =====
SELECT
    to_regclass('public.rider_offer_alert') IS NOT NULL AS r1_table_present,                                           -- true
    EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'job_rider_offer_alerts') AS r1_job_present,                         -- true
    EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'rider_offer_alert' AND column_name = 'cycle') AS cycle_present,       -- false (first run)
    EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'rider_offer_alert' AND column_name = 'round_at') AS round_at_present, -- false (first run)
    (SELECT count(*) FROM cron.job WHERE jobname = 'job_rider_offer_alerts' AND active) AS cron_active;                -- 1

-- ===== STEP 1: COLUMNS, BACKFILL, INDEXES =====
-- cycle: reminder rows only. How many offers of the order were 'declined' when this reminder cycle was seeded. The job starts
--        a new cycle for an open offer when the order's decline count is higher than the offer's latest cycle. Escalations: 0.
ALTER TABLE public.rider_offer_alert
    ADD COLUMN IF NOT EXISTS cycle integer NOT NULL DEFAULT 0;

-- round_at: escalation rows only. Which dispatch round the escalation belongs to: delivery_summary.redispatch_dtts of the
--           round, or '-infinity' for the first dispatch. Reminders: '-infinity' (a reminder belongs to one offer row, and a
--           cancel before pickup deletes the other offer rows, so a new round always means new dispatch_ids).
ALTER TABLE public.rider_offer_alert
    ADD COLUMN IF NOT EXISTS round_at timestamp with time zone NOT NULL DEFAULT '-infinity'::timestamptz;

COMMENT ON COLUMN public.rider_offer_alert.cycle IS 'reminder: number of declined offers of the order when this reminder cycle started (a higher count restarts the cycle); escalation: 0';

COMMENT ON COLUMN public.rider_offer_alert.round_at IS 'escalation: delivery_summary.redispatch_dtts of the dispatch round, -infinity for the first round; reminder: -infinity';

-- Backfill: existing reminder rows get the order's CURRENT decline count, so applying r2 never restarts an offer by itself.
-- Existing escalation rows keep '-infinity' (first round). Re-running is harmless (same values).
UPDATE
    public.rider_offer_alert a
SET
    cycle = x.declines
FROM (
    SELECT
        d.order_number::text AS order_number,
        count(*)::int AS declines
    FROM
        public.delivery_dispatch d
    WHERE
        d.status = 'declined'
    GROUP BY
        d.order_number) x
WHERE
    a.kind = 'reminder'
    AND a.order_number = x.order_number
    AND a.cycle IS DISTINCT FROM x.declines
    AND NOT EXISTS (
        SELECT
            1
        FROM
            public.rider_offer_alert b
        WHERE
            b.kind = 'reminder'
            AND b.dispatch_id = a.dispatch_id
            AND b.cycle > 0);

-- New unique keys first, then drop the r1 ones (each statement stands alone).
CREATE UNIQUE INDEX IF NOT EXISTS rider_offer_alert_reminder_cycle_uidx ON public.rider_offer_alert USING btree (dispatch_id, cycle, offset_secs)
WHERE (kind = 'reminder'::text);

CREATE UNIQUE INDEX IF NOT EXISTS rider_offer_alert_escalation_round_uidx ON public.rider_offer_alert USING btree (order_number, round_at)
WHERE (kind = 'escalation'::text);

DROP INDEX IF EXISTS public.rider_offer_alert_reminder_uidx;

DROP INDEX IF EXISTS public.rider_offer_alert_escalation_uidx;

-- ===== STEP 2: THE JOB =====
-- job_rider_offer_alerts() -> boolean (r2). Every 5 seconds (pg_cron 'job_rider_offer_alerts').
--   OFFSETS  parse_alert_offsets('RIDER_OFFER_ALERT_OFFSETS_SECS'), > 0 only; NULL = OFF (cancel all pending, seed nothing).
--   SEED     for every open Telegram offer (unassigned, < 15 min old, rider_offer_state() 'open'), with D = how many offers
--            of its order are 'declined' now and L = the offer's latest reminder cycle (NULL = never seeded):
--              L IS NULL -> FIRST cycle:   cycle D, due = offer time (dtts) + offset
--              D > L     -> RESTART cycle: the offer's pending rows 'superseded', then cycle D, due = now() + offset
--            ("now()" is the database clock when the job first sees the decline, within 5 s of it; status_update_dtts is
--            not used: Python writes it with the app server's local clock).
--            escalation: one per order AND round. Round start = delivery_summary.redispatch_dtts (cancel before pickup) or
--            -infinity; due = the round's first Telegram offer + the LAST offset. Declines never move it.
--   CANCEL   pending reminders whose offer is not 'open'; pending escalations whose order is no longer open.
--   DUE      one reminder per offer (largest due offset); every due escalation with its round's offered / declined counts and
--            redispatched = (round_at > -infinity).
--   POST     /rider-hooks/offer-alerts {reminders:[{dispatch_id,n,of}], escalations:[{order_number,after_secs,offered,declined,redispatched}]}
--   MARK     only on 2xx: due losers 'superseded' first, then due rows 'sent'.
CREATE OR REPLACE FUNCTION public.job_rider_offer_alerts ()
    RETURNS boolean
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_offsets int[];
    v_last int;
    v_reminders jsonb;
    v_escalations jsonb;
    v_payload jsonb;
    v_app_url text;
    v_hook_url text;
    v_resp http_response;
BEGIN
    SELECT
        array_agg(o ORDER BY o) INTO v_offsets
    FROM
        unnest(public.parse_alert_offsets ('RIDER_OFFER_ALERT_OFFSETS_SECS')) AS o
    WHERE
        o > 0;
    IF v_offsets IS NULL THEN
        -- ---- OFF: cancel everything pending, seed nothing ---------------------------------------------------
        UPDATE
            public.rider_offer_alert
        SET
            status = 'cancelled',
            swept_at = now()
        WHERE
            status = 'pending';
        RETURN TRUE;
    END IF;
    v_last := v_offsets[cardinality(v_offsets)];
    -- ---- SEED reminders: first cycle for new offers; a new cycle when the order's decline count went up ------
    WITH o AS (
        SELECT
            d.dispatch_id,
            d.order_number::text AS order_number,
            d.rider_id::text AS rider_id,
            d.dtts::timestamptz AS offered_at,
            (
                SELECT
                    count(*)::int
                FROM
                    public.delivery_dispatch x
                WHERE
                    x.order_number = d.order_number
                    AND x.status = 'declined') AS declines,
            (
                SELECT
                    max(a.cycle)
                FROM
                    public.rider_offer_alert a
                WHERE
                    a.kind = 'reminder'
                    AND a.dispatch_id = d.dispatch_id) AS last_cycle
        FROM
            public.delivery_dispatch d
        WHERE
            d.channel = 'telegram'
            AND d.status = 'unassigned'
            AND d.dtts > (now() - interval '15 minutes')::timestamp
            AND (public.rider_offer_state (d.dispatch_id) ->> 'state') = 'open'
),
todo AS (
    SELECT
        *
    FROM
        o
    WHERE
        o.last_cycle IS NULL
        OR o.declines > o.last_cycle
),
restarted AS (
    UPDATE
        public.rider_offer_alert a
    SET
        status = 'superseded',
        swept_at = now()
    FROM
        todo t
    WHERE
        t.last_cycle IS NOT NULL
        AND a.kind = 'reminder'
        AND a.dispatch_id = t.dispatch_id
        AND a.status = 'pending'
    RETURNING
        a.id)
INSERT INTO public.rider_offer_alert (kind, order_number, dispatch_id, rider_id, offset_secs, n, of_n, due_at, cycle)
SELECT
    'reminder',
    t.order_number,
    t.dispatch_id,
    t.rider_id,
    off.v,
    off.n::int,
    cardinality(v_offsets),
    (
        CASE WHEN t.last_cycle IS NULL THEN
            t.offered_at
        ELSE
            now()
        END) + off.v * interval '1 second',
    t.declines
FROM
    todo t
    CROSS JOIN LATERAL unnest(v_offsets)
    WITH ORDINALITY AS off (v, n)
ON CONFLICT (dispatch_id,
    cycle,
    offset_secs)
WHERE (kind = 'reminder')
    DO NOTHING;
    -- ---- SEED escalation: once per order AND dispatch round, due after the round's first Telegram offer + last offset ----
    INSERT INTO public.rider_offer_alert (kind, order_number, offset_secs, n, of_n, due_at, round_at)
    SELECT
        'escalation',
        d.order_number::text,
        v_last,
        1,
        1,
        min(d.dtts)::timestamptz + v_last * interval '1 second',
        COALESCE(s.redispatch_dtts, '-infinity'::timestamptz)
    FROM
        public.delivery_dispatch d
        JOIN public.delivery_summary s ON s.order_number = d.order_number
    WHERE
        d.channel = 'telegram'
        AND d.dtts > (now() - interval '15 minutes')::timestamp
        AND d.dtts::timestamptz >= COALESCE(s.redispatch_dtts, '-infinity'::timestamptz)
        AND public.rider_offer_order_open (d.order_number::text)
    GROUP BY
        d.order_number,
        s.redispatch_dtts
    ON CONFLICT (order_number,
        round_at)
WHERE (kind = 'escalation')
    DO NOTHING;
    -- ---- CANCEL: the offer (or the order) stopped being open before its checkpoint fell due ---------------------
    UPDATE
        public.rider_offer_alert a
    SET
        status = 'cancelled',
        swept_at = now()
    WHERE
        a.status = 'pending'
        AND ((a.kind = 'reminder'
                AND (public.rider_offer_state (a.dispatch_id) ->> 'state') <> 'open')
            OR (a.kind = 'escalation'
                AND NOT public.rider_offer_order_open (a.order_number)));
    -- ---- DUE: one reminder per offer (the largest due offset) and every due escalation --------------------------
    SELECT
        jsonb_agg(jsonb_build_object('dispatch_id', w.dispatch_id, 'n', w.n, 'of', w.of_n) ORDER BY w.dispatch_id) INTO v_reminders
    FROM (
        SELECT
            a.*,
            row_number() OVER (PARTITION BY a.dispatch_id ORDER BY a.cycle DESC, a.offset_secs DESC) AS rn
        FROM
            public.rider_offer_alert a
        WHERE
            a.status = 'pending'
            AND a.kind = 'reminder'
            AND a.due_at <= now()) w
WHERE
    w.rn = 1;
    SELECT
        jsonb_agg(jsonb_build_object('order_number', a.order_number, 'after_secs', a.offset_secs, 'redispatched', a.round_at > '-infinity'::timestamptz, 'offered', (
                    SELECT
                        count(*)
                    FROM public.delivery_dispatch d
                    WHERE
                        d.order_number = a.order_number
                        AND d.channel = 'telegram'
                        AND d.dtts::timestamptz >= a.round_at), 'declined', (
                    SELECT
                        count(*)
                    FROM public.delivery_dispatch d
                    WHERE
                        d.order_number = a.order_number
                        AND d.channel = 'telegram'
                        AND d.status = 'declined'
                        AND d.dtts::timestamptz >= a.round_at))
        ORDER BY a.order_number) INTO v_escalations
    FROM
        public.rider_offer_alert a
    WHERE
        a.status = 'pending'
        AND a.kind = 'escalation'
        AND a.due_at <= now();
    IF v_reminders IS NULL AND v_escalations IS NULL THEN
        RETURN TRUE;
        -- nothing to say: the endpoint is not called at all
    END IF;
    -- ---- POST ---------------------------------------------------------------------------------------------------
    v_payload := jsonb_build_object('event_type', 'rider_offer_alerts', 'timestamp', extract(epoch FROM now()), 'reminders', COALESCE(v_reminders, '[]'::jsonb), 'escalations', COALESCE(v_escalations, '[]'::jsonb));
    SELECT
        config_value INTO v_app_url
    FROM
        public.ordelo_config
    WHERE
        config_key = 'ORDELO_APP_URL';
    IF v_app_url IS NULL OR length(v_app_url) = 0 THEN
        v_app_url := 'https://agent.ordelo.app';
    END IF;
    IF RIGHT (v_app_url, 1) = '/' THEN
        v_app_url := LEFT (v_app_url, length(v_app_url) - 1);
    END IF;
    v_hook_url := v_app_url || '/rider-hooks/offer-alerts';
    SELECT
        * INTO v_resp
    FROM
        http_post (v_hook_url, v_payload::text, 'application/json');
    IF v_resp.status IS NULL OR v_resp.status < 200 OR v_resp.status > 299 THEN
        RAISE NOTICE 'job_rider_offer_alerts: POST to % returned %, leaving checkpoints pending', v_hook_url, v_resp.status;
        RETURN FALSE;
    END IF;
    -- ---- MARK, only on 2xx. ORDER MATTERS: supersede FIRST (see job_t_order_alerts / job_rider_pickup_alerts) ------
    UPDATE
        public.rider_offer_alert a
    SET
        status = 'superseded',
        swept_at = now()
    FROM (
        SELECT
            x.id,
            row_number() OVER (PARTITION BY x.dispatch_id ORDER BY x.cycle DESC, x.offset_secs DESC) AS rn
        FROM
            public.rider_offer_alert x
        WHERE
            x.status = 'pending'
            AND x.kind = 'reminder'
            AND x.due_at <= now()) r
WHERE
    a.id = r.id
        AND r.rn > 1;
    UPDATE
        public.rider_offer_alert a
    SET
        status = 'sent',
        swept_at = now()
    WHERE
        a.status = 'pending'
        AND a.due_at <= now();
    RETURN TRUE;
END
$$;

REVOKE ALL ON FUNCTION public.job_rider_offer_alerts () FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.job_rider_offer_alerts () TO service_role;

COMMENT ON FUNCTION public.job_rider_offer_alerts () IS 'Every 5 seconds: seed (restarting an offer''s reminders after a decline), cancel, find due Telegram offer reminders and per-round overwatch escalations, POST them, and mark them on success.';

-- ===== STEP 3: VERIFY (expect true / true / 2 / 0 / 0) =====
SELECT
    EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'rider_offer_alert' AND column_name = 'cycle') AS cycle_present,       -- true
    EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'rider_offer_alert' AND column_name = 'round_at') AS round_at_present, -- true
    (SELECT count(*) FROM pg_indexes WHERE tablename = 'rider_offer_alert'
        AND indexname IN ('rider_offer_alert_reminder_cycle_uidx', 'rider_offer_alert_escalation_round_uidx')) AS r2_indexes,  -- 2
    (SELECT count(*) FROM pg_indexes WHERE tablename = 'rider_offer_alert'
        AND indexname IN ('rider_offer_alert_reminder_uidx', 'rider_offer_alert_escalation_uidx')) AS r1_indexes_left,         -- 0
    (SELECT count(*) FROM information_schema.role_routine_grants
      WHERE routine_name = 'job_rider_offer_alerts' AND grantee IN ('anon', 'authenticated', 'PUBLIC')) AS public_grants;     -- 0

-- ===== WATCH (read only) =====
-- SELECT kind, order_number, dispatch_id, cycle, round_at, offset_secs, n, due_at, status, swept_at
--   FROM public.rider_offer_alert WHERE order_number LIKE 'STRK-TEST-%' ORDER BY kind DESC, dispatch_id, cycle, offset_secs;
