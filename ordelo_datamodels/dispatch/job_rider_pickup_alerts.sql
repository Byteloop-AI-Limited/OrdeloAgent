-- See also (paths under ordelo_datamodels/): the same rider/ops/restaurant alerts also reach Telegram admins through the notifier; the Telegram receipts and notices are in restaurant_admin/restaurant_ready_adjust_notices.sql.
/**
================================================================================
  RIDER, OPS & RESTAURANT-ADMIN PICKUP ALERTS
  Nudges a rider around their pickup time, and escalates to ops and the
  restaurant's admins -- on separate schedules -- when ignored.
================================================================================

WHAT THIS FILE CREATES
--------------------------------------------------------------------------------
  TABLE     rider_pickup_alert                the ledger: one row per checkpoint
  FUNCTION  parse_alert_offsets(text)         one config key -> sorted int[]
  FUNCTION  job_rider_pickup_alerts()         the sweep; pg_cron runs it every 2 min
  FUNCTION  rider_pickup_alert_reschedule()   trigger body
  TRIGGER   trigger_pickup_time_reschedule    on delivery_summary.pickup_time
  6 rows in ordelo_config                     one interval list per bucket


THE IDEA
--------------------------------------------------------------------------------
Every alert is a CHECKPOINT: "N minutes from this order's pickup time, tell
someone". N is a signed integer -- negative is before pickup, positive is after.
Each checkpoint becomes one row in rider_pickup_alert, which records when it
falls due and whether it has fired. That ledger is the whole memory of the
feature; nothing lives in agent state.

Checkpoints come in six BUCKETS, one per (audience x phase):

  AUDIENCE = who hears it            PHASE = where the delivery must be
    rider        -> via the agent      awaiting_pickup -> dispatch is 'assigned'
    ops          -> overwatch          picked_up       -> dispatch is 'pickedup'
    rest_admins  -> the restaurant's admins

  ┌─────────────┬─────────────────┬──────────────────────────────────────────────┬───────────────┐
  │ audience    │ phase           │ ordelo_config key                            │ default       │
  ├─────────────┼─────────────────┼──────────────────────────────────────────────┼───────────────┤
  │ rider       │ awaiting_pickup │ ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS      │ -15,-5,2,5,7  │
  │ rider       │ picked_up       │ ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS    │ 30,45         │
  │ ops         │ awaiting_pickup │ rider_alert_to_overwatch_pickup_intervals    │ 10            │
  │ ops         │ picked_up       │ rider_alert_to_overwatch_delivery_intervals  │ 30            │
  │ rest_admins │ awaiting_pickup │ rider_alert_to_rest_admins_pickup_intervals  │ -10,2,7       │
  │ rest_admins │ picked_up       │ rider_alert_to_rest_admins_delivery_intervals│ (blank = off) │
  └─────────────┴─────────────────┴──────────────────────────────────────────────┴───────────────┘

  Blank any key to switch off just that bucket. Blank all six and the job does
  nothing at all. The rest_admins/picked_up key ships blank on purpose -- wired
  end to end, inactive until someone sets it.

ALL SIX BUCKETS MEASURE FROM delivery_summary.pickup_time -- never from the
moment the rider actually collected. That one anchor is why a single trigger can
reschedule everything when an admin moves the pickup time.


WORKED EXAMPLE  (defaults above, pickup_time = 12:00)
--------------------------------------------------------------------------------
  11:45  rider:       "pickup is in about 15 min"     <- rider checkpoint -15
  11:50  rest_admins: "rider due to collect at 12:00" <- rest_admins checkpoint -10
  11:55  rider:       "pickup is in about 5 min"      <- rider checkpoint -5
  12:02  rider:       "you're about 2 min past pickup" <- rider checkpoint 2       }  same
         rest_admins: "not yet collected, 2 min past"  <- rest_admins checkpoint 2 }  tick
  12:07  rider:       "you're about 7 min past pickup" <- rider checkpoint 7       }  same
         rest_admins: "not yet collected, 7 min past"  <- rest_admins checkpoint 7 }  tick
  12:10  ops:         "rider has still not collected"  <- ops checkpoint 10
  12:30  ops:         "collected but not delivered"    <- ops checkpoint 30  }  same
         rider:       "you're about 30 min past pickup" <- rider checkpoint 30 }  tick

The 12:07/12:10 cluster is the case to keep in mind: three audiences, and rider
and rest_admins share the SAME offset (7). They are separate checkpoints,
partitioned by audience, and all fire independently.


HOW THE SWEEP RUNS  (job_rider_pickup_alerts, every 2 minutes)
--------------------------------------------------------------------------------
  (a) read the six config keys         -> nothing configured? stop
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
-- (The statement that followed this comment is now generated from live in dispatch/rider_pickup_alert.sql.)

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
-- (The statement that followed this comment is now generated from live in dispatch/rider_pickup_alert.sql.)

-- ===========================================================================
-- 2. CONFIG -- one interval list per bucket
--    Edit these to change the schedule; no code change needed.
-- ===========================================================================
-- The ops and rest_admins keys are lowercase to match the `overwatch_list` key
-- they sit beside. Deliberately inconsistent with the uppercase rider keys.
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
   'Minutes past delivery_summary.pickup_time at which to alert overwatch that a rider has still not collected. Blank disables.'),
  ('rider_alert_to_overwatch_delivery_intervals',
   '30',
   'Minutes past delivery_summary.pickup_time at which to alert overwatch that a collected order is still undelivered. Blank disables.'),
  ('rider_alert_to_rest_admins_pickup_intervals',
   '-10,2,7',
   'Signed minutes around delivery_summary.pickup_time at which to message the restaurant''s admins about the rider; negative = heads-up before pickup, positive = chase after. Blank disables.'),
  ('rider_alert_to_rest_admins_delivery_intervals',
   '',
   'Minutes after delivery_summary.pickup_time at which to tell the restaurant''s admins a collected order is still undelivered. BLANK ON PURPOSE = inactive; set e.g. 30 to enable. Do not use a placeholder word -- an unparseable non-blank value logs a NOTICE on every sweep.')
ON CONFLICT (config_key) DO NOTHING;

-- ===========================================================================
-- 4. job_rider_pickup_alerts() -- the sweep
--    Steps (a) read config, (b) seed, (c) resolve, (d) post, (e) mark.
--    Returns false when it did nothing useful, true otherwise.
-- ===========================================================================
CREATE OR REPLACE FUNCTION job_rider_pickup_alerts()
RETURNS boolean AS $$
DECLARE
    v_rider_pickup         int[];
    v_rider_delivery       int[];
    v_ops_pickup           int[];
    v_ops_delivery         int[];
    v_rest_admins_pickup   int[];
    v_rest_admins_delivery int[];
    v_alerts               jsonb;
    v_payload              jsonb;
    v_app_url              text;
    v_hook_url             text;
    v_resp                 http_response;
    v_cfg                  record;
BEGIN
    PERFORM set_config('statement_timeout', '10000', true);

    -- ---- (a) READ CONFIG -------------------------------------------------
    -- A blank or absent key disables that bucket.
    v_rider_pickup         := parse_alert_offsets('ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS');
    v_rider_delivery       := parse_alert_offsets('ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS');
    v_ops_pickup           := parse_alert_offsets('rider_alert_to_overwatch_pickup_intervals');
    v_ops_delivery         := parse_alert_offsets('rider_alert_to_overwatch_delivery_intervals');
    v_rest_admins_pickup   := parse_alert_offsets('rider_alert_to_rest_admins_pickup_intervals');
    v_rest_admins_delivery := parse_alert_offsets('rider_alert_to_rest_admins_delivery_intervals');

    -- Set but unparseable is an operator mistake, not a kill switch -- say so
    -- loudly. This is the NOTICE you want the first time an alert goes missing.
    FOR v_cfg IN
        SELECT c.config_key, c.config_value
          FROM ordelo_config c
         WHERE c.config_key IN (
                   'ORDELO_APP_RIDER_PICKUP_ALERT_INTERVALS',
                   'ORDELO_APP_RIDER_DELIVERY_ALERT_INTERVALS',
                   'rider_alert_to_overwatch_pickup_intervals',
                   'rider_alert_to_overwatch_delivery_intervals',
                   'rider_alert_to_rest_admins_pickup_intervals',
                   'rider_alert_to_rest_admins_delivery_intervals')
           AND btrim(c.config_value) <> ''
           AND parse_alert_offsets(c.config_key) IS NULL
    LOOP
        RAISE NOTICE 'job_rider_pickup_alerts: config "%" = "%" contains no valid integers',
                     v_cfg.config_key, v_cfg.config_value;
    END LOOP;

    IF v_rider_pickup IS NULL AND v_rider_delivery IS NULL
       AND v_ops_pickup IS NULL AND v_ops_delivery IS NULL
       AND v_rest_admins_pickup IS NULL AND v_rest_admins_delivery IS NULL THEN
        RAISE NOTICE 'job_rider_pickup_alerts: no intervals configured in any bucket, skipping';
        RETURN false;
    END IF;

    -- ---- (b) SEED --------------------------------------------------------
    -- Create the missing checkpoint rows for every live dispatch. The VALUES
    -- list below IS the six-bucket table from the header, in code.
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
         ('rider'::varchar,       'awaiting_pickup'::varchar, 'assigned'::varchar, v_rider_pickup),
         ('rider'::varchar,       'picked_up'::varchar,       'pickedup'::varchar, v_rider_delivery),
         ('ops'::varchar,         'awaiting_pickup'::varchar, 'assigned'::varchar, v_ops_pickup),
         ('ops'::varchar,         'picked_up'::varchar,       'pickedup'::varchar, v_ops_delivery),
         ('rest_admins'::varchar, 'awaiting_pickup'::varchar, 'assigned'::varchar, v_rest_admins_pickup),
         ('rest_admins'::varchar, 'picked_up'::varchar,       'pickedup'::varchar, v_rest_admins_delivery)
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
    -- degrades the ops/rest_admins message rather than dropping the alert.
    -- Rider rows ignore those columns.
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

-- pg_cron job 'job_rider_pickup_alert' (live schedule: */5 * * * *, active). cron.schedule() updates the job in place when the name already exists.
SELECT cron.schedule('job_rider_pickup_alert', '*/5 * * * *', $cron$select job_rider_pickup_alerts();$cron$);

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

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
-- 0b. All six keys present, and overwatch_list populated? An empty
--     overwatch_list means ops escalations are lost, not redirected -- ops is
--     overwatch-only now. rider_alert_to_rest_admins_delivery_intervals is
--     expected BLANK; that is the inactive default, not a missing row.
-- SELECT config_key, config_value FROM ordelo_config
--  WHERE config_key LIKE 'ORDELO_APP_RIDER_%_ALERT_INTERVALS'
--     OR config_key LIKE 'rider_alert_to_%'
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
-- --- rider + rest_admins alerts, before collection (dispatch 'assigned') --
--
-- 3. Four minutes to pickup. The wording always comes from the REAL delta, not
--    the checkpoint's offset -- so both messages say "4 min", not the
--    checkpoint numbers (-5 / -10) that triggered them. Expect ONE rider
--    message ("in about 4 min") and ONE rest_admins message ("due to collect
--    ... in ~4 min"; its only due checkpoint is -10, but -10 is a bucket
--    label, not a promise about the wording).
--    Rider: -15 superseded, -5 sent, 2/5/7 pending.
--    rest_admins: -10 sent, 2/7 pending. No ops alert (10 not due).
-- UPDATE delivery_summary SET pickup_time = now() + interval '4 minutes'
--  WHERE order_number = '<ORDER>';
-- SELECT job_rider_pickup_alerts();
--
-- 4. Re-run at once. Expect silence and no status changes.
-- SELECT job_rider_pickup_alerts();
--
-- 5. Six minutes past pickup. The step-3 UPDATE reopened everything, so expect
--    ONE rider message ("about 6 min past") and ONE rest_admins message
--    ("6 min past", its 2 checkpoint firing since 7 is not yet due).
--    Rider: -15/-5/2 superseded, 5 sent, 7 pending.
--    rest_admins: -10 superseded, 2 sent, 7 pending. Still no ops alert.
-- UPDATE delivery_summary SET pickup_time = now() - interval '6 minutes'
--  WHERE order_number = '<ORDER>';
-- SELECT job_rider_pickup_alerts();
--
-- --- ops escalation #1 + rest_admins chase, still uncollected -------------
--
-- 6. THE SHARPEST CHECK IN THIS FILE. Eleven minutes past pickup. rider/7,
--    ops/10, and rest_admins/7 are all due at once -- three audiences, one
--    tick, and rider/rest_admins share offset_minutes = 7. This is exactly
--    the case the 4-column PK and PARTITION BY (dispatch_id, audience) exist
--    for. Expect THREE messages from ONE run:
--      * rider, via the agent: "about 11 min past pickup"
--      * overwatch (🔴, via WALogger): "still not collected"
--      * the restaurant's admins (⏰): "has not yet collected -- 11 min past"
--    ops/awaiting_pickup/10 and rest_admins/awaiting_pickup/7 both go 'sent'.
--    If only two messages arrive, check which audience went missing before
--    assuming the ranking is broken -- confirm it isn't a config gap first.
-- UPDATE delivery_summary SET pickup_time = now() - interval '11 minutes'
--  WHERE order_number = '<ORDER>';
-- SELECT job_rider_pickup_alerts();
--
-- --- after collection (drive the dispatch to 'pickedup' first) ------------
--
-- 7. Verify the restaurant confirmation code through the agent so the
--    dispatch flips to 'pickedup' the real way, then go 31 minutes past
--    pickup. Both the rider delivery bucket (offset 30) and the ops delivery
--    bucket (offset 30) are due -- two rows, same offset, different audience.
--    Expect TWO messages from ONE run: one to the rider via the agent, one to
--    overwatch. rest_admins/picked_up seeds and fires NOTHING here -- its key
--    ships blank; see step 8b to exercise that branch deliberately.
-- UPDATE delivery_summary SET pickup_time = now() - interval '31 minutes'
--  WHERE order_number = '<ORDER>';
-- SELECT job_rider_pickup_alerts();
--
-- --- switches and failure modes -------------------------------------------
--
-- 8. Independent kill switches. Blank all non-rider keys: rider alerts must
--    still fire and nothing reaches overwatch or the restaurant. Then restore
--    and blank both rider keys to check the reverse.
-- UPDATE ordelo_config SET config_value = ''
--  WHERE config_key LIKE 'rider_alert_to_%';
-- SELECT job_rider_pickup_alerts();
-- UPDATE ordelo_config SET config_value = '10'
--  WHERE config_key = 'rider_alert_to_overwatch_pickup_intervals';
-- UPDATE ordelo_config SET config_value = '30'
--  WHERE config_key = 'rider_alert_to_overwatch_delivery_intervals';
-- UPDATE ordelo_config SET config_value = '-10,2,7'
--  WHERE config_key = 'rider_alert_to_rest_admins_pickup_intervals';
-- UPDATE ordelo_config SET config_value = ''
--  WHERE config_key = 'rider_alert_to_rest_admins_delivery_intervals';
--
-- 8b. Wake the dormant bucket. rest_admins/picked_up is the one branch no
--     runbook step or normal traffic will ever exercise while its key is
--     blank -- flip it on, exercise it once, then blank it again. On a
--     'pickedup' dispatch, 31 minutes past pickup:
-- UPDATE ordelo_config SET config_value = '30'
--  WHERE config_key = 'rider_alert_to_rest_admins_delivery_intervals';
-- UPDATE delivery_summary SET pickup_time = now() - interval '31 minutes'
--  WHERE order_number = '<ORDER>';
-- SELECT job_rider_pickup_alerts();
--    Expect the restaurant's admins to get "🛵 ... collected but has not
--    delivered -- 31 min past". Then:
-- UPDATE ordelo_config SET config_value = ''
--  WHERE config_key = 'rider_alert_to_rest_admins_delivery_intervals';
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
-- 11. Full kill switch. Blank all six interval keys -> returns false, no HTTP
--     call at all.
--
-- 12. Replay a test order from the top.
-- UPDATE rider_pickup_alert SET status = 'pending', sent_dtts = NULL
--  WHERE order_number = '<ORDER>';
----------------------------- END VERIFICATION -----------------------------
-- select job_rider_pickup_alerts();
