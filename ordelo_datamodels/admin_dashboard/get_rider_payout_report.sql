-- =============================================================================================
-- ordelo_datamodels/admin_dashboard/get_rider_payout_report.sql
-- Rider payout report: one row per completed dispatch in a date window, with rider identity and bank details.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     get_rider_payout_report(p_start date, p_end date, p_exclude_riders text[]) -> TABLE(dispatch_id bigint, order_number text, rest_ref text, rider_id text, rider_name text, town text, vehicle_type text, bank_account_name text, sort_code text, bank_account text, rider_payout double precision, distance double precision, dtts timestamp without time zone, paid_status text, paid_dtts timestamp without time zone)
--                   Return one payable row per completed dispatch between p_start and p_end, excluding the given rider ids.
-- REQUIRES      dispatch/delivery_dispatch.sql
--               delivery/delivery_summary.sql
--               core/rider_master.sql
--               core/rider_registrations.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none (read-only).
-- HOW IT FITS   Backs GET /sys-admin/rider-payout (watomation/routers/sys_admin_auth_session.py get_rider_payout), used by the
--                 sys-admin "Rider Payouts" page in restaurant-frontend, which then calls POST /sys-admin/update-paid per dispatch
--                 (delivery_dispatch.paid_status / paid_dtts). Reads delivery_dispatch, delivery_summary, rider_master and
--                 rider_registrations (bank details). The detailed reasoning (why it replaced a Python-side join) is in the comment below.
-- LIFECYCLE     none
-- CALLED BY     get_rider_payout_report:
--                 python    watomation/routers/sys_admin_auth_session.py: get_rider_payout()
-- PYTHON MODEL  none
-- SECURITY      get_rider_payout_report(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       none
-- SEE ALSO      dispatch/delivery_dispatch.sql (paid_status)
--               core/rider_registrations.sql
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function get_rider_payout_report(p_start date, p_end date, p_exclude_riders text[]) -> TABLE(dispatch_id bigint, order_number text, rest_ref text, rider_id text, rider_name text, town text, vehicle_type text, bank_account_name text, sort_code text, bank_account text, rider_payout double precision, distance double precision, dtts timestamp without time zone, paid_status text, paid_dtts timestamp without time zone)
--   Return one payable row per completed dispatch between p_start and p_end, excluding the given rider ids.
--   Data: reads delivery_dispatch, delivery_summary, rider_master, rider_registrations.
-- ---------------------------------------------------------------------------------------------
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
DROP FUNCTION IF EXISTS get_rider_payout_report (DATE, DATE, TEXT[]);

CREATE OR REPLACE FUNCTION get_rider_payout_report (p_start date, p_end date, p_exclude_riders text[] DEFAULT '{}')
    RETURNS TABLE (
        dispatch_id bigint,
        order_number text,
        rest_ref text,
        rider_id text,
        rider_name text,
        town text,
        vehicle_type text,
        bank_account_name text,
        sort_code text,
        bank_account text,
        rider_payout double precision,
        distance double precision,
        dtts timestamp,
        paid_status text,
        paid_dtts timestamp
    )
    AS $$
    -- One bank record per rider, digits-only phone match, newest registration wins.
    WITH rider_bank AS (
        SELECT DISTINCT ON (regexp_replace(reg.phone, '[^0-9]', '', 'g')
)
            regexp_replace(reg.phone, '[^0-9]', '', 'g') AS norm_phone,
            reg.bank_account_name,
            reg.sort_code,
            reg.bank_account
        FROM
            rider_registrations reg
        WHERE
            reg.phone IS NOT NULL
        ORDER BY
            regexp_replace(reg.phone, '[^0-9]', '', 'g'),
            reg.inserted_at DESC NULLS LAST
)
    SELECT
        d.dispatch_id::bigint,
        d.order_number::text,
        ds.rest_ref::text,
        d.rider_id::text,
        rm.rider_name::text,
        rm.town::text,
        d.vehicle_type::text,
        rb.bank_account_name::text,
        rb.sort_code::text,
        rb.bank_account::text,
        d.rider_payout,
        d.distance,
        d.dtts,
        d.paid_status::text,
        d.paid_dtts
    FROM
        delivery_dispatch d
    LEFT JOIN rider_master rm ON rm.rider_id = d.rider_id
    LEFT JOIN delivery_summary ds ON ds.order_number = d.order_number
    LEFT JOIN rider_bank rb ON rb.norm_phone = d.rider_id
WHERE
    d.status = 'completed'
    AND d.dtts >= p_start::timestamp
    AND d.dtts < (p_end + 1)::timestamp
    AND NOT (d.rider_id = ANY (COALESCE(p_exclude_riders, ARRAY[]::text[])))
ORDER BY
    d.dtts DESC;
$$
LANGUAGE sql
STABLE;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.get_rider_payout_report (p_start date, p_end date, p_exclude_riders text[]) IS 'Return one payable row per completed dispatch between p_start and p_end, excluding the given rider ids.';

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
