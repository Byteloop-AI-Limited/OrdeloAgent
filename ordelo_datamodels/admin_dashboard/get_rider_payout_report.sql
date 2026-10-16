/**
Rider Payout Report – sys-admin weekly payout sourcing

Where This Fits in the Journey:
    - Runs *after* the delivery workflow has finished (dispatch status='completed').
    - Backs `GET /sys-admin/rider-payout`, consumed by the sys-admin "Rider Payouts"
      dashboard page which then calls `POST /sys-admin/update-paid` per dispatch.

Purpose:
    - Return one row per completed dispatch in [p_start, p_end] with the rider's
      identity, location and bank details, ready for aggregation by payee.
    - Replaces the previous Python-side join in `watomation/routers/sys_admin_auth_session.py`,
      which silently dropped payable rows. The bugs this function fixes:
      1. `delivery_option` was keyed in Python by `order_number` alone. That table holds
         one row per vehicle type per order (bicycle/car/scooter/electric_bike), so the
         dict collapsed 3-4 rows down to whichever came back last and then required it to
         equal the rider's vehicle type. Most rows failed that accidental comparison.
         Orpington (BNAT) orders price 4 vehicle types vs Salisbury's 3, so they lost more
         often - which is why the report looked like it was "Salisbury only".
         `delivery_option` is no longer joined at all: `delivery_dispatch.vehicle_type` is
         NOT NULL and is the authoritative vehicle for the job, so the join added no
         columns and could only drop rows.
      2. Rider bank details were matched with `phone[1:]`, i.e. "strip the leading +".
         Numbers stored as '+44 7765522420 ' never matched rider_id '447765522420'.
         Now normalised to digits-only on both sides.
      3. `rider_registrations` holds duplicate rows for some riders; DISTINCT ON keeps
         the most recently inserted one instead of an arbitrary dict winner.
      4. The end of the range was compared as `dtts <= 'YYYY-MM-DD'`, i.e. midnight, so
         the whole final day was excluded and the dashboard's "Today" preset was always
         empty. `p_end` is now inclusive of the entire day.
    - Joins are LEFT so that a missing rider_master / delivery_summary / registration row
      surfaces a payout with NULL bank details instead of silently deleting money owed.

Parameters:
    - p_start          : first day of the window, inclusive.
    - p_end            : last day of the window, inclusive (whole day).
    - p_exclude_riders : rider_ids to omit (internal test accounts). The caller owns this
                         list so it can change without a DB migration.

Dependencies:
    - Reads from: `delivery_dispatch`, `rider_master`, `delivery_summary`, `rider_registrations`.
    - Writes: none. Declared STABLE.

Invocation:
    SELECT * FROM get_rider_payout_report('2026-09-12', '2026-09-18', ARRAY['447448440754']);

    -- via PostgREST / supabase-py
    client_ordelo.rpc("get_rider_payout_report", {
        "p_start": "2026-09-12", "p_end": "2026-09-18",
        "p_exclude_riders": ["447448440754"],
    }).execute()

Deployment note:
    After applying this file, reload the PostgREST schema cache so the RPC is exposed:
        NOTIFY pgrst, 'reload schema';
**/

----------------------------------------
-- get_rider_payout_report - completed dispatches with payee details
----------------------------------------
DROP FUNCTION IF EXISTS get_rider_payout_report(DATE, DATE, TEXT[]);

CREATE OR REPLACE FUNCTION get_rider_payout_report(
    p_start          DATE,
    p_end            DATE,
    p_exclude_riders TEXT[] DEFAULT '{}'
)
RETURNS TABLE (
    dispatch_id       BIGINT,
    order_number      TEXT,
    rest_ref          TEXT,
    rider_id          TEXT,
    rider_name        TEXT,
    town              TEXT,
    vehicle_type      TEXT,
    bank_account_name TEXT,
    sort_code         TEXT,
    bank_account      TEXT,
    rider_payout      DOUBLE PRECISION,
    distance          DOUBLE PRECISION,
    dtts              TIMESTAMP,
    paid_status       TEXT,
    paid_dtts         TIMESTAMP
) AS $$
    -- One bank record per rider, digits-only phone match, newest registration wins.
    WITH rider_bank AS (
        SELECT DISTINCT ON (regexp_replace(reg.phone, '[^0-9]', '', 'g'))
               regexp_replace(reg.phone, '[^0-9]', '', 'g') AS norm_phone,
               reg.bank_account_name,
               reg.sort_code,
               reg.bank_account
        FROM   rider_registrations reg
        WHERE  reg.phone IS NOT NULL
        ORDER  BY regexp_replace(reg.phone, '[^0-9]', '', 'g'),
                  reg.inserted_at DESC NULLS LAST
    )
    SELECT d.dispatch_id::BIGINT,
           d.order_number::TEXT,
           ds.rest_ref::TEXT,
           d.rider_id::TEXT,
           rm.rider_name::TEXT,
           rm.town::TEXT,
           d.vehicle_type::TEXT,
           rb.bank_account_name::TEXT,
           rb.sort_code::TEXT,
           rb.bank_account::TEXT,
           d.rider_payout,
           d.distance,
           d.dtts,
           d.paid_status::TEXT,
           d.paid_dtts
    FROM   delivery_dispatch d
    LEFT   JOIN rider_master     rm ON rm.rider_id  = d.rider_id
    LEFT   JOIN delivery_summary ds ON ds.order_number = d.order_number
    LEFT   JOIN rider_bank       rb ON rb.norm_phone   = d.rider_id
    WHERE  d.status = 'completed'
      AND  d.dtts >= p_start::TIMESTAMP
      AND  d.dtts <  (p_end + 1)::TIMESTAMP
      AND  NOT (d.rider_id = ANY (COALESCE(p_exclude_riders, ARRAY[]::TEXT[])))
    ORDER  BY d.dtts DESC;
$$ LANGUAGE sql STABLE;

----------------------------------------
-- Sanity checks (run manually after applying)
----------------------------------------
-- Every completed dispatch in the window must appear exactly once, minus excluded riders:
-- SELECT count(*) FROM delivery_dispatch
--  WHERE status='completed' AND dtts >= '2026-08-20' AND dtts < '2026-09-21'
--    AND rider_id <> '447448440754';
-- SELECT count(*) FROM get_rider_payout_report('2026-08-20','2026-09-20',ARRAY['447448440754']);
--
-- Riders we owe money to but hold no bank details for:
-- SELECT DISTINCT rider_id, rider_name, town
--   FROM get_rider_payout_report('2026-08-20','2026-09-20',ARRAY['447448440754'])
--  WHERE bank_account IS NULL;
