/**
================================================================================
  RIDER & OPS PICKUP ALERTS
  Nudges a rider around their pickup time, and escalates to ops when ignored.
================================================================================

WHAT THIS FILE CREATES
--------------------------------------------------------------------------------
  TABLE     rider_pickup_alert                the ledger: one row per checkpoint
  FUNCTION  parse_alert_offsets(text)         one config key -> sorted int[]
  FUNCTION  job_rider_pickup_alerts()         the sweep; pg_cron runs it every 2 min
  FUNCTION  rider_pickup_alert_reschedule()   trigger body
  TRIGGER   trigger_pickup_time_reschedule    on delivery_summary.pickup_time
  4 rows in ordelo_config                     one interval list per bucket


THE IDEA
--------------------------------------------------------------------------------
Every alert is a CHECKPOINT: "N minutes from this order's pickup time, tell
someone". N is a signed integer -- negative is before pickup, positive is after.
Each checkpoint becomes one row in rider_pickup_alert, which records when it
falls due and whether it has fired. That ledger is the whole memory of the
feature; nothing lives in agent state.

Checkpoints come in four BUCKETS, one per (audience x phase):

  AUDIENCE = who hears it       PHASE = where the delivery must be
    rider  -> via the agent       awaiting_pickup -> dispatch is 'assigned'
    ops    -> overwatch + admins  picked_up       -> dispatch is 'pickedup'

  ┌──────────┬─────────────────┬───────────────────────────────────────────┬───────────────┐
  │ audience │ phase           │ ordelo_config key                         │ default       │
  ├──────────┼─────────────────┼───────────────────────────────────────────┼───────────────┤
  │ rider    │ awaiting_pickup │ ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS   │ -15,-5,2,5,7  │
  │ rider    │ picked_up       │ ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS │ 30,45         │
  │ ops      │ awaiting_pickup │ rider_alert_to_overwatch_pickup_intervals │ 10            │
  │ ops      │ picked_up       │ rider_alert_to_overwatch_delivery_intervals│ 30           │
  └──────────┴─────────────────┴───────────────────────────────────────────┴───────────────┘

  Blank any key to switch off just that bucket. Blank all four and the job does
  nothing at all.

ALL FOUR BUCKETS MEASURE FROM delivery_summary.pickup_time -- never from the
moment the rider actually collected. That one anchor is why a single trigger can
reschedule everything when an admin moves the pickup time.


WORKED EXAMPLE  (defaults above, pickup_time = 12:00)
--------------------------------------------------------------------------------
  11:45  rider: "pickup is in about 15 min"          <- checkpoint -15
  11:55  rider: "pickup is in about 5 min"           <- checkpoint -5
  12:02  rider: "you're about 2 min past pickup"     <- checkpoint 2
  12:10  ops:   "rider has still not collected"      <- ops checkpoint 10
  12:30  ops:   "collected but not delivered"        <- ops checkpoint 30  }  same
         rider: "you're about 30 min past pickup"    <- rider checkpoint 30 }  tick

The 12:30 line is the case to keep in mind: two rows, same offset, different
audience. They are separate checkpoints and both fire.


HOW THE SWEEP RUNS  (job_rider_pickup_alerts, every 2 minutes)
--------------------------------------------------------------------------------
  (a) read the four config keys        -> nothing configured? stop
  (b) SEED   create missing checkpoint rows for live dispatches
  (c) RESOLVE pick what is due now, one winner per (dispatch, audience)
  (d) POST   send them to /delivery-hooks/rider-pickup-alerts -- only if any
  (e) MARK   on a 2xx: winner -> 'sent', the ones it overtook -> 'superseded'

COLLAPSE-TO-MAX. If several checkpoints in a bucket came due at once -- a cron
outage, or a rider who collected long after the pickup time -- only the LARGEST
fires; the rest are marked 'superseded'. The largest is the most recently passed
one, so it is the truest description of "now", and marking the others stops the
next tick sending "7 min late" after "10 min late".

AT-LEAST-ONCE. The whole sweep is one transaction and nothing is marked until
the endpoint answers 2xx, so a failed POST leaves the rows 'pending' and the next
tick retries.

CADENCE. The cron interval must be <= the smallest gap between two offsets in
any bucket, or they collapse into one alert. The defaults contain 5 and 7, hence
every 2 minutes.


RUNBOOK
--------------------------------------------------------------------------------
Step-by-step checks to run before scheduling the cron are at the bottom of this
file, under VERIFICATION.

See also: docs/delivery_process.md, CONTEXT.md ("Pickup alert").
**/


-- ===========================================================================
-- 1. THE LEDGER
--    One row per checkpoint. Answers "what was sent, what is still to come".
-- ===========================================================================
CREATE TABLE IF NOT EXISTS rider_pickup_alert (
    dispatch_id    INTEGER      NOT NULL
                   REFERENCES delivery_dispatch(dispatch_id) ON DELETE CASCADE,
    phase          VARCHAR(20)  NOT NULL
                   CHECK (phase IN ('awaiting_pickup', 'picked_up')),
    audience       VARCHAR(20)  NOT NULL
                   CHECK (audience IN ('rider', 'ops')),
    offset_minutes INTEGER      NOT NULL,
    order_number   VARCHAR(100) NOT NULL,
    rider_id       VARCHAR(12)  NOT NULL,
    status         VARCHAR(20)  NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'sent', 'superseded')),
    due_dtts       TIMESTAMP WITH TIME ZONE NOT NULL,
    sent_dtts      TIMESTAMP WITH TIME ZONE,
    dt             DATE NOT NULL DEFAULT CURRENT_DATE,
    dtts           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (dispatch_id, phase, audience, offset_minutes)
);

-- Column notes:
--   status    pending    -> due in the future, or not yet swept
--             sent       -> the message went out
--             superseded -> came due but a later checkpoint spoke instead
--   due_dtts  pickup_time + offset_minutes. Rewritten by the trigger in §4
--             whenever pickup_time moves.
--
-- The 4-column key is what lets a rider row and an ops row share an offset.
-- phase/audience have no DEFAULT on purpose: the seeding INSERT is the only
-- writer and always names both, so a future caller that forgets one fails loudly
-- instead of landing in the wrong bucket.
--
-- Rows are never cleaned up here. ON DELETE CASCADE does it: every path that
-- removes a delivery (cleanup_delivery_order, dispatch_cancel_before_pickup, the
-- test-reset scripts) deletes delivery_dispatch first. Rows for finished
-- deliveries are kept deliberately as the audit trail.

CREATE INDEX IF NOT EXISTS rider_pickup_alert_due_idx
    ON rider_pickup_alert (status, due_dtts);

CREATE INDEX IF NOT EXISTS rider_pickup_alert_order_idx
    ON rider_pickup_alert (order_number);


-- ===========================================================================
-- 2. CONFIG -- one interval list per bucket
--    Edit these to change the schedule; no code change needed.
-- ===========================================================================
-- The two ops keys are lowercase to match the `overwatch_list` key they sit
-- beside. Deliberately inconsistent with the uppercase rider keys.
INSERT INTO ordelo_config (config_key, config_value, description)
VALUES
  ('ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS',
   '-15,-5,2,5,7',
   'Signed minutes around delivery_summary.pickup_time at which to alert a rider who has not yet collected; negative = before pickup, positive = after. Blank disables awaiting-pickup rider alerts.'),
  ('ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS',
   '30,45',
   'Minutes after delivery_summary.pickup_time at which to chase a rider who has collected but not delivered. Blank disables in-transit rider alerts.'),
  ('rider_alert_to_overwatch_pickup_intervals',
   '10',
   'Minutes past delivery_summary.pickup_time at which to alert overwatch and restaurant admins that a rider has still not collected. Blank disables.'),
  ('rider_alert_to_overwatch_delivery_intervals',
   '30',
   'Minutes past delivery_summary.pickup_time at which to alert overwatch and restaurant admins that a collected order is still undelivered. Blank disables.')
ON CONFLICT (config_key) DO NOTHING;


-- ===========================================================================
-- 3. parse_alert_offsets(config_key) -> int[]
--    '-15, -5, x, 5' -> {-15,-5,5}.  Absent/blank/all-junk -> NULL.
-- ===========================================================================
-- Junk entries are skipped rather than fatal: one stray character must not
-- silence alerts for every rider. The caller tells "absent" from "present but
-- unparseable" and RAISEs a NOTICE for the latter.
CREATE OR REPLACE FUNCTION parse_alert_offsets(p_config_key text)
RETURNS int[]
LANGUAGE sql
STABLE
AS $$
    SELECT array_agg(DISTINCT btrim(t.x)::int ORDER BY btrim(t.x)::int)
      FROM ordelo_config c
     CROSS JOIN unnest(string_to_array(c.config_value, ',')) AS t(x)
     WHERE c.config_key = p_config_key
       AND btrim(t.x) ~ '^-?\d+$';
$$;


-- ===========================================================================
-- 4. job_rider_pickup_alerts() -- the sweep
--    Steps (a) read config, (b) seed, (c) resolve, (d) post, (e) mark.
--    Returns false when it did nothing useful, true otherwise.
-- ===========================================================================
CREATE OR REPLACE FUNCTION job_rider_pickup_alerts()
RETURNS boolean AS $$
DECLARE
    v_rider_pickup     int[];
    v_rider_delivery   int[];
    v_ops_pickup       int[];
    v_ops_delivery     int[];
    v_alerts           jsonb;
    v_payload          jsonb;
    v_app_url          text;
    v_hook_url         text;
    v_resp             http_response;
    v_cfg              record;
BEGIN
    PERFORM set_config('statement_timeout', '10000', true);

    -- ---- (a) READ CONFIG -------------------------------------------------
    -- A blank or absent key disables that bucket.
    v_rider_pickup   := parse_alert_offsets('ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS');
    v_rider_delivery := parse_alert_offsets('ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS');
    v_ops_pickup     := parse_alert_offsets('rider_alert_to_overwatch_pickup_intervals');
    v_ops_delivery   := parse_alert_offsets('rider_alert_to_overwatch_delivery_intervals');

    -- Set but unparseable is an operator mistake, not a kill switch -- say so
    -- loudly. This is the NOTICE you want the first time an alert goes missing.
    FOR v_cfg IN
        SELECT c.config_key, c.config_value
          FROM ordelo_config c
         WHERE c.config_key IN (
                   'ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS',
                   'ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS',
                   'rider_alert_to_overwatch_pickup_intervals',
                   'rider_alert_to_overwatch_delivery_intervals')
           AND btrim(c.config_value) <> ''
           AND parse_alert_offsets(c.config_key) IS NULL
    LOOP
        RAISE NOTICE 'job_rider_pickup_alerts: config "%" = "%" contains no valid integers',
                     v_cfg.config_key, v_cfg.config_value;
    END LOOP;

    IF v_rider_pickup IS NULL AND v_rider_delivery IS NULL
       AND v_ops_pickup IS NULL AND v_ops_delivery IS NULL THEN
        RAISE NOTICE 'job_rider_pickup_alerts: no intervals configured in any bucket, skipping';
        RETURN false;
    END IF;

    -- ---- (b) SEED --------------------------------------------------------
    -- Create the missing checkpoint rows for every live dispatch. The VALUES
    -- list below IS the four-bucket table from the header, in code.
    --
    -- Two behaviours worth knowing:
    --   * NOT EXISTS is scoped per (dispatch, phase, audience), so the
    --     picked_up rows appear only when the dispatch flips to 'pickedup' --
    --     that is what makes them start counting at collection.
    --   * Because it is NOT EXISTS rather than ON CONFLICT, editing a config
    --     mid-delivery never injects new checkpoints into a bucket already
    --     under way. A delivery keeps the schedule it started with.
    --   * A NULL offsets array unnests to zero rows, so a disabled bucket
    --     seeds nothing.
    INSERT INTO rider_pickup_alert (
        dispatch_id, phase, audience, order_number, rider_id, offset_minutes, due_dtts
    )
    SELECT di.dispatch_id,
           ph.phase,
           ph.audience,
           di.order_number,
           di.rider_id,
           k.offset_minutes,
           ds.pickup_time + (k.offset_minutes * interval '1 minute')
      FROM delivery_inflight di
      JOIN delivery_dispatch dd ON dd.dispatch_id  = di.dispatch_id
      JOIN delivery_summary  ds ON ds.order_number = di.order_number
     -- Plain CROSS JOIN, not LATERAL: the VALUES list depends on plpgsql
     -- variables, not on the row to its left. Casts keep gate_status varchar.
     CROSS JOIN (VALUES
         ('rider'::varchar, 'awaiting_pickup'::varchar, 'assigned'::varchar, v_rider_pickup),
         ('rider'::varchar, 'picked_up'::varchar,       'pickedup'::varchar, v_rider_delivery),
         ('ops'::varchar,   'awaiting_pickup'::varchar, 'assigned'::varchar, v_ops_pickup),
         ('ops'::varchar,   'picked_up'::varchar,       'pickedup'::varchar, v_ops_delivery)
     ) AS ph(audience, phase, gate_status, offsets)
     CROSS JOIN unnest(ph.offsets) AS k(offset_minutes)
     WHERE dd.status = ph.gate_status
       AND ds.pickup_time IS NOT NULL
       AND NOT EXISTS (
               SELECT 1
                 FROM rider_pickup_alert a
                WHERE a.dispatch_id = di.dispatch_id
                  AND a.phase       = ph.phase
                  AND a.audience    = ph.audience
           );

    -- ---- (c) RESOLVE -----------------------------------------------------
    -- Rank the due checkpoints; rn = 1 is the winner, rn > 1 got overtaken.
    -- Partitioning by audience as well as dispatch is what lets a rider alert
    -- and an ops alert fire on the same tick instead of suppressing each other.
    --
    -- A CTE, not a TEMP TABLE: pg_cron reuses sessions and plpgsql caches plans
    -- against the dropped relation, so the second run would fail with
    -- "relation with OID ... does not exist".
    --
    -- restaurant_master / rider_master are LEFT joined so a missing row only
    -- degrades the ops message rather than dropping the alert. Rider rows
    -- ignore those columns.
    WITH phases AS (
        SELECT * FROM (VALUES
            ('awaiting_pickup'::varchar, 'assigned'::varchar),
            ('picked_up'::varchar,       'pickedup'::varchar)
        ) AS p(phase, gate_status)
    ),
    ranked AS (
        SELECT a.dispatch_id,
               a.phase,
               a.audience,
               a.offset_minutes,
               a.order_number,
               a.rider_id,
               ds.pickup_time,
               ds.rest_name,
               ds.rest_ref,
               rm.admins      AS rest_admins,
               rdr.rider_name,
               row_number() OVER (PARTITION BY a.dispatch_id, a.audience
                                  ORDER BY a.offset_minutes DESC) AS rn
          FROM rider_pickup_alert a
          JOIN phases            p  ON p.phase         = a.phase
          JOIN delivery_inflight di ON di.dispatch_id  = a.dispatch_id
          JOIN delivery_dispatch dd ON dd.dispatch_id  = a.dispatch_id
                                   AND dd.status       = p.gate_status
          JOIN delivery_summary  ds ON ds.order_number = a.order_number
          LEFT JOIN restaurant_master rm  ON rm.rest_id   = ds.rest_id
          LEFT JOIN rider_master      rdr ON rdr.rider_id = a.rider_id
         WHERE a.status   = 'pending'
           AND a.due_dtts <= now()
    )
    SELECT jsonb_agg(
               jsonb_build_object(
                   'order_number',         r.order_number,
                   'rider_id',             r.rider_id,
                   'rider_name',           r.rider_name,
                   'dispatch_id',          r.dispatch_id,
                   'phase',                r.phase,
                   'audience',             r.audience,
                   'offset_minutes',       r.offset_minutes,
                   'pickup_time',          r.pickup_time,
                   'rest_name',            r.rest_name,
                   'rest_ref',             r.rest_ref,
                   'rest_admins',          r.rest_admins,
                   'minutes_since_pickup',
                       round((EXTRACT(EPOCH FROM (now() - r.pickup_time)) / 60.0)::numeric, 1)
               )
           )
      INTO v_alerts
      FROM ranked r
     WHERE r.rn = 1;

    -- Nothing due anywhere: the endpoint is not called at all.
    IF v_alerts IS NULL THEN
        RETURN true;
    END IF;

    -- ---- (d) POST --------------------------------------------------------
    v_payload := jsonb_build_object(
        'event_type', 'rider_pickup_alerts',
        'timestamp',  extract(epoch from now()),
        'alerts',     v_alerts
    );

    SELECT config_value INTO v_app_url
      FROM ordelo_config
     WHERE config_key = 'ORDELO_APP_URL';

    IF v_app_url IS NULL OR length(v_app_url) = 0 THEN
        v_app_url := 'https://agent.ordelo.app';
    END IF;

    -- Ensure no trailing slash before appending path
    IF right(v_app_url, 1) = '/' THEN
        v_app_url := left(v_app_url, length(v_app_url) - 1);
    END IF;
    v_hook_url := v_app_url || '/delivery-hooks/rider-pickup-alerts';

    SELECT * INTO v_resp
      FROM http_post(v_hook_url, v_payload::text, 'application/json');

    IF v_resp.status IS NULL OR v_resp.status < 200 OR v_resp.status > 299 THEN
        RAISE NOTICE 'job_rider_pickup_alerts: POST to % returned %, leaving checkpoints pending',
                     v_hook_url, v_resp.status;
        RETURN false;
    END IF;

    -- ---- (e) MARK, only on 2xx -------------------------------------------
    -- now() is fixed for the transaction, so re-running `ranked` here sees
    -- exactly the rows step (c) saw.
    --
    -- ORDER MATTERS: supersede FIRST. Marking winners 'sent' first would drop
    -- them out of `ranked` (it filters status='pending'), re-rank the
    -- survivors, and leave the new rn = 1 unmarked -- which then fires as a
    -- stale alert next tick.
    --
    -- This CTE carries fewer joins than step (c) ON PURPOSE -- it selects
    -- nothing from delivery_summary / restaurant_master / rider_master, and
    -- dropping them cannot change the row set. Do not "sync" the two.
    WITH phases AS (
        SELECT * FROM (VALUES
            ('awaiting_pickup'::varchar, 'assigned'::varchar),
            ('picked_up'::varchar,       'pickedup'::varchar)
        ) AS p(phase, gate_status)
    ),
    ranked AS (
        SELECT a.dispatch_id,
               a.phase,
               a.audience,
               a.offset_minutes,
               row_number() OVER (PARTITION BY a.dispatch_id, a.audience
                                  ORDER BY a.offset_minutes DESC) AS rn
          FROM rider_pickup_alert a
          JOIN phases            p  ON p.phase        = a.phase
          JOIN delivery_inflight di ON di.dispatch_id = a.dispatch_id
          JOIN delivery_dispatch dd ON dd.dispatch_id = a.dispatch_id
                                   AND dd.status      = p.gate_status
         WHERE a.status   = 'pending'
           AND a.due_dtts <= now()
    )
    UPDATE rider_pickup_alert a
       SET status = 'superseded'
      FROM ranked r
     WHERE a.dispatch_id    = r.dispatch_id
       AND a.phase          = r.phase
       AND a.audience       = r.audience
       AND a.offset_minutes = r.offset_minutes
       AND r.rn > 1
       AND a.status = 'pending';

    -- Winners are driven off the payload itself, so the marked set can never
    -- drift from the set actually sent.
    UPDATE rider_pickup_alert a
       SET status    = 'sent',
           sent_dtts = now()
      FROM jsonb_array_elements(v_alerts) AS j(alert)
     WHERE a.dispatch_id    = (j.alert ->> 'dispatch_id')::int
       AND a.phase          = (j.alert ->> 'phase')
       AND a.audience       = (j.alert ->> 'audience')
       AND a.offset_minutes = (j.alert ->> 'offset_minutes')::int
       AND a.status         = 'pending';

    RETURN true;

EXCEPTION
    WHEN OTHERS THEN
        -- The EXCEPTION block wraps the body in a subtransaction, so a raise
        -- here (http_post to a dead host, say) also rolls back the step (b)
        -- seed. Harmless -- the next tick re-seeds identically -- but it means
        -- a dead ORDELO_APP_URL leaves the ledger EMPTY rather than
        -- seeded-but-unsent. VERIFICATION step 10 checks this.
        RAISE NOTICE 'Error in job_rider_pickup_alerts: %', SQLERRM;
        RETURN false;
END;
$$ LANGUAGE plpgsql;


-- ===========================================================================
-- 5. RESCHEDULE -- keep the ledger honest when pickup_time moves
--    Any change to delivery_summary.pickup_time re-times and reopens every
--    checkpoint for that order.
-- ===========================================================================
-- One trigger covers all four buckets with no phase or audience logic, because
-- they all hang off the same anchor. It catches every path that moves the time:
-- the admin /AdminAdjustPickupTime button, the restaurant-timeout auto-set in
-- _handle_restaurant_timedout, and manual SQL.
--
-- It updates by order_number, which is safe only because the FK cascades: an
-- order cancelled pre-pickup and re-dispatched has lost its old
-- delivery_dispatch row, and the old ledger went with it.
--
-- Two consequences to expect while testing:
--   * A tiny adjustment reopens already-sent checkpoints, so the rider (and
--     ops) may get one repeat of the most recent one. Accepted -- they were
--     just told the time changed.
--   * An awaiting_pickup row still 'pending' when the rider collects is
--     reopened too, but can never fire again: the phase gate in (c) requires
--     dd.status = 'assigned' and the dispatch is now 'pickedup'.
CREATE OR REPLACE FUNCTION rider_pickup_alert_reschedule()
RETURNS trigger AS $$
BEGIN
    UPDATE rider_pickup_alert a
       SET due_dtts  = NEW.pickup_time + (a.offset_minutes * interval '1 minute'),
           status    = 'pending',
           sent_dtts = NULL
     WHERE a.order_number = NEW.order_number;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- The first NULL -> value set fires this too, harmlessly: no rows exist yet.
CREATE OR REPLACE TRIGGER trigger_pickup_time_reschedule
AFTER UPDATE OF pickup_time ON public.delivery_summary
FOR EACH ROW
WHEN (NEW.pickup_time IS DISTINCT FROM OLD.pickup_time)
EXECUTE FUNCTION rider_pickup_alert_reschedule();


-- ===========================================================================
-- 6. SCHEDULE -- run this once, after the VERIFICATION steps below pass
-- ===========================================================================
-- Interval must be <= the smallest gap between two offsets in any bucket. The
-- defaults contain 5 and 7, so */2. At */5 those two collapse into one alert.
--
-- SELECT cron.schedule('job_rider_pickup_alerts', '*/2 * * * *',
--                      $$SELECT job_rider_pickup_alerts()$$);
--
-- SELECT cron.unschedule('job_rider_pickup_alerts');


----------------------------- VERIFICATION -----------------------------
-- Run by hand against one test dispatch, in order, before scheduling the cron.
-- The app must be running with ORDELO_APP_URL pointing at it.
--
-- --- setup ---------------------------------------------------------------
--
-- 0. Pre-flight. Does parse_alert_offsets already exist with a DIFFERENT
--    signature? CREATE OR REPLACE across a changed return type errors and takes
--    the whole migration with it. Expect zero rows, or exactly
--    parse_alert_offsets(text) returning integer[].
-- SELECT p.oid::regprocedure::text AS signature, pg_get_function_result(p.oid) AS returns
--   FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
--  WHERE n.nspname = 'public' AND p.proname = 'parse_alert_offsets';
--
-- 0b. All four keys present, and overwatch_list populated? An empty
--     overwatch_list means ops escalations reach the restaurant admins only.
-- SELECT config_key, config_value FROM ordelo_config
--  WHERE config_key LIKE 'ORDELO_APP_RIDER_%_ALERT_INTERVALS'
--     OR config_key LIKE 'rider_alert_to_overwatch_%'
--     OR config_key = 'overwatch_list';
--
-- 1. Pick a live dispatch to test against.
-- SELECT di.dispatch_id, di.order_number, di.rider_id, dd.status, ds.pickup_time
--   FROM delivery_inflight di
--   JOIN delivery_dispatch dd ON dd.dispatch_id  = di.dispatch_id
--   JOIN delivery_summary  ds ON ds.order_number = di.order_number
--  WHERE dd.status IN ('assigned', 'pickedup');
--
-- 2. The ledger. Re-run this after every step below.
-- SELECT audience, phase, offset_minutes, status, due_dtts, sent_dtts
--   FROM rider_pickup_alert
--  WHERE order_number = '<ORDER>'
--  ORDER BY audience, phase, offset_minutes;
--
-- --- rider alerts, before collection (dispatch still 'assigned') ----------
--
-- 3. Four minutes to pickup. Expect ONE rider message ("in about 4 min"),
--    -15 superseded, -5 sent, 2/5/7 pending. No ops alert (10 not due).
-- UPDATE delivery_summary SET pickup_time = now() + interval '4 minutes'
--  WHERE order_number = '<ORDER>';
-- SELECT job_rider_pickup_alerts();
--
-- 4. Re-run at once. Expect silence and no status changes.
-- SELECT job_rider_pickup_alerts();
--
-- 5. Six minutes past pickup. The step-3 UPDATE reopened everything, so expect
--    ONE rider message ("about 6 min past"), -15/-5/2 superseded, 5 sent,
--    7 pending. Still no ops alert.
-- UPDATE delivery_summary SET pickup_time = now() - interval '6 minutes'
--  WHERE order_number = '<ORDER>';
-- SELECT job_rider_pickup_alerts();
--
-- --- ops escalation #1, still uncollected ---------------------------------
--
-- 6. Eleven minutes past pickup. Expect overwatch AND the restaurant's admins
--    to get one 🔴 "still not collected" message, and ops/awaiting_pickup/10
--    to go 'sent'. Re-run: silent.
-- UPDATE delivery_summary SET pickup_time = now() - interval '11 minutes'
--  WHERE order_number = '<ORDER>';
-- SELECT job_rider_pickup_alerts();
--
-- --- after collection (drive the dispatch to 'pickedup' first) ------------
--
-- 7. THE SHARPEST CHECK IN THIS FILE. Verify the restaurant confirmation code
--    through the agent so the dispatch flips to 'pickedup' the real way, then
--    go 31 minutes past pickup. Both the rider delivery bucket (offset 30) and
--    the ops delivery bucket (offset 30) are due -- two rows, same offset,
--    different audience. Expect TWO messages from ONE run: one to the rider via
--    the agent, one to overwatch + admins. If only one arrives, the ranking is
--    not partitioning by audience.
-- UPDATE delivery_summary SET pickup_time = now() - interval '31 minutes'
--  WHERE order_number = '<ORDER>';
-- SELECT job_rider_pickup_alerts();
--
-- --- switches and failure modes -------------------------------------------
--
-- 8. Independent kill switches. Blank both ops keys: rider alerts must still
--    fire and nothing reaches overwatch. Then restore and blank both rider keys
--    to check the reverse.
-- UPDATE ordelo_config SET config_value = ''
--  WHERE config_key LIKE 'rider_alert_to_overwatch_%';
-- SELECT job_rider_pickup_alerts();
-- UPDATE ordelo_config SET config_value = '10'
--  WHERE config_key = 'rider_alert_to_overwatch_pickup_intervals';
-- UPDATE ordelo_config SET config_value = '30'
--  WHERE config_key = 'rider_alert_to_overwatch_delivery_intervals';
--
-- 9. Alerts stop after delivery. Complete the order, re-run, confirm nothing is
--    sent and any remaining rows stay 'pending' and inert.
--
-- 10. Unreachable app. The POST raises, the EXCEPTION handler rolls back the
--     subtransaction, and the seed is undone with it -- so for a brand-new
--     dispatch the ledger stays EMPTY. Expect false, no rows, and a clean
--     re-seed once the URL is restored. (An app that is up but erroring takes
--     the non-2xx branch instead: false, rows left 'pending'.)
-- UPDATE ordelo_config SET config_value = 'http://127.0.0.1:9' WHERE config_key = 'ORDELO_APP_URL';
-- SELECT job_rider_pickup_alerts();
-- SELECT count(*) FROM rider_pickup_alert WHERE order_number = '<ORDER>';
-- UPDATE ordelo_config SET config_value = '<REAL URL>' WHERE config_key = 'ORDELO_APP_URL';
--
-- 11. Full kill switch. Blank all four interval keys -> returns false, no HTTP
--     call at all.
--
-- 12. Replay a test order from the top.
-- UPDATE rider_pickup_alert SET status = 'pending', sent_dtts = NULL
--  WHERE order_number = '<ORDER>';
----------------------------- END VERIFICATION -----------------------------
select job_rider_pickup_alerts();