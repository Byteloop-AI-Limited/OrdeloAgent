-- MIGRATION (history; do not edit the statements below)
-- Applied to live: 2026-10-27 (owner-confirmed)
-- Current definitions now live in: dispatch/job_rider_offer_alerts.sql (job); dispatch/rider_offer_alert.sql (column comments)
-- Purpose: rider offer reminders r3 (plans/rider-dispatch-alerts-plan.md, section 12).
--          A Decline with nobody having accepted NO LONGER restarts the other riders' reminders (r2 behaviour removed).
--          Every offer is seeded ONCE, when it first becomes open: 7 reminders at offer time + each offset.
--          Accept-then-decline before pickup is unchanged and still gives a complete reset: dispatch_cancel_before_pickup()
--          deletes the order's other offers and job_create_dispatch() inserts brand-new offers (new dispatch_ids), which are
--          first-time offers, so each gets the full schedule from zero, and a new overwatch round starts (redispatch_dtts).
--          Kept from r2: one overwatch escalation per dispatch round.
--          No dispatch logic changes: job_create_dispatch, job_assign_dispatch, process_delivery and
--          dispatch_cancel_before_pickup are not touched. No table or index change.
-- Requires: migrations/rider_offer_alerts.sql (r1) and migrations/rider_offer_alerts_r2.sql (r2) applied (2026-10-27).

/*
HOW TO APPLY (Supabase SQL editor, one block at a time, in this order; no BEGIN/COMMIT):

  STEP 0  PRE-CHECK (read only): r2 is in place (true / true / true / 1).
  STEP 1  The new job_rider_offer_alerts() (CREATE OR REPLACE; safe to re-run). The cron job keeps running the whole time;
          its next run uses the new body. Nothing to reschedule.
  STEP 2  Column comment for `cycle` (cosmetic, safe to re-run).
  STEP 3  VERIFY: true / false.
  STEP 4  python scripts/datamodels/drift_check.py
  STEP 5  Live test: test_restaurant_notices.sql STAGE 2c (steps f and g, updated for r3).

  No deploy is needed for this migration: the Python code and the POST payload are unchanged.
  The cron job job_rider_offer_alerts is ALREADY scheduled. Do not schedule it again.

BEHAVIOUR NOTES
  - Rows already in the ledger are left alone. Pending rows of a cycle that r2 restarted still fire; nothing is deleted.
  - The `cycle` column stays (and its unique index): new rows always get cycle 0, so (dispatch_id, cycle, offset_secs) is
    still unique per offer. Old rows keep the cycle value r2 gave them.

ROLLBACK (only if needed):
  Re-apply STEP 1 of migrations/rider_offer_alerts_r2.sql (CREATE OR REPLACE brings the restart behaviour back). Nothing else changes.
*/

-- ===== STEP 0: PRE-CHECK (read only) =====
SELECT
    to_regclass('public.rider_offer_alert') IS NOT NULL AS table_present,                                              -- true
    EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'rider_offer_alert' AND column_name = 'cycle') AS cycle_present,       -- true
    EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'rider_offer_alert' AND column_name = 'round_at') AS round_at_present, -- true
    (SELECT count(*) FROM cron.job WHERE jobname = 'job_rider_offer_alerts' AND active) AS cron_active;                -- 1

-- ===== STEP 1: job_rider_offer_alerts() (r3) =====
-- job_rider_offer_alerts() -> boolean (r3). Every 5 seconds (pg_cron 'job_rider_offer_alerts').
--   OFFSETS  parse_alert_offsets('RIDER_OFFER_ALERT_OFFSETS_SECS'), > 0 only; NULL = OFF (cancel all pending, seed nothing).
--   SEED     reminders: for every open Telegram offer (unassigned, < 15 min old, rider_offer_state() 'open') that has NO
--            reminder row yet: cycle 0, due = offer time (dtts) + offset. Never re-seeded: a decline does not restart anything.
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
    -- ---- SEED reminders: once per offer, when it first becomes open (r3: a decline never restarts) ---------
    WITH o AS (
        SELECT
            d.dispatch_id,
            d.order_number::text AS order_number,
            d.rider_id::text AS rider_id,
            d.dtts::timestamptz AS offered_at,
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
)
INSERT INTO public.rider_offer_alert (kind, order_number, dispatch_id, rider_id, offset_secs, n, of_n, due_at, cycle)
SELECT
    'reminder',
    t.order_number,
    t.dispatch_id,
    t.rider_id,
    off.v,
    off.n::int,
    cardinality(v_offsets),
    t.offered_at + off.v * interval '1 second',
    0
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

COMMENT ON FUNCTION public.job_rider_offer_alerts () IS 'Every 5 seconds: seed (once per offer), cancel, find due Telegram offer reminders and per-round overwatch escalations, POST them, and mark them on success.';

-- ===== STEP 2: COLUMN COMMENT (cosmetic) =====
COMMENT ON COLUMN public.rider_offer_alert.cycle IS 'reminder: 0 for every row seeded since r3 (older rows carry the r2 decline count); the unique index (dispatch_id, cycle, offset_secs) still holds. escalation: 0';

-- ===== STEP 3: VERIFY =====
SELECT
    EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'job_rider_offer_alerts'
             AND prosrc LIKE '%last_cycle IS NULL%') AS seeds_once,                                                    -- true
    EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'job_rider_offer_alerts'
             AND prosrc LIKE '%restarted AS%') AS still_restarts;                                                     -- false
