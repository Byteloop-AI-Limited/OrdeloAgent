-- =============================================================================================
-- ordelo_datamodels/admin_dashboard/get_rider_jobs.sql
-- Session-authorized rider jobs, full-filter earnings and a masked profile.
-- =============================================================================================
-- LIVE CHECK    New functions, not applied. UTC database timezone and recent dispatch offsets checked read-only 2026-10-26.
-- OBJECTS       fn     get_rider_jobs(p_cookie_hash text, p_ua_hash text, p_tab text, p_from date, p_to date, p_paid text, p_cursor_time timestamptz, p_cursor_id integer, p_limit integer) -> jsonb
--                   One statement snapshot of rider jobs, aggregates and pagination; no customer details.
--               fn     get_rider_profile(p_cookie_hash text, p_ua_hash text) -> jsonb
--                   Read only the session rider's name/town/vehicle and masked bank account suffix.
-- REQUIRES      admin_dashboard/auth_sessions.sql
--               dispatch/delivery_dispatch.sql
--               delivery/delivery_summary.sql
--               core/rider_registrations.sql
--               restaurant-agents: food_order
-- HOW TO RUN    Owner applies after auth_sessions.sql; functions are idempotent. No live execution by agents.
-- SIDE EFFECTS  none; read-only functions, no delivery or payout transition.
-- HOW IT FITS   restaurant-frontend/lib/rider-jobs.ts calls the jobs RPC for SSR and GET /api/rider/jobs.
-- LIFECYCLE     Current assigned/pickedup amounts are expected; only completed dispatches count as earned.
-- CALLED BY     restaurant-frontend/lib/rider-jobs.ts; restaurant-frontend/app/rider/more/page.tsx
-- PYTHON MODEL  none
-- SECURITY      Service-role only; cookie and UA hashes authorize the principal, never a supplied rider ID.
-- TESTS         tests/sql/test_rider_dashboard_sql.py
-- GOTCHAS       Dispatch timestamps are UTC without timezone; London day bounds are converted explicitly.
--               No test/channel-specific financial rule; report the stored completed dispatch payout.
-- SEE ALSO      admin_dashboard/get_rider_payout_report.sql
-- =============================================================================================

-- get_rider_jobs: typed inputs, one snapshot for rows/summary; cursor affects rows only.
-- Returns result ok | invalid | bad_input | bad_data and {tab,rows,summary,nextCursor,asOf} on success.
-- Reads auth_sessions/rider_master for authorization, dispatches for money, summary/order only for allowed enrichment.
CREATE OR REPLACE FUNCTION public.get_rider_jobs (p_cookie_hash text, p_ua_hash text, p_tab text, p_from date DEFAULT NULL, p_to date DEFAULT NULL, p_paid text DEFAULT 'all', p_cursor_time timestamptz DEFAULT NULL, p_cursor_id integer DEFAULT NULL, p_limit integer DEFAULT 25)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    SET timezone = 'UTC'
    AS $$
    WITH session AS MATERIALIZED (
        SELECT
            rider_dashboard_session (
                p_cookie_hash, p_ua_hash
) AS value
),
    valid AS (
        SELECT
            coalesce(p_tab IN ('current', 'completed')
                AND p_paid IN ('all', 'paid', 'unpaid')
                AND p_limit BETWEEN 1 AND 50
                AND ((p_cursor_time IS NULL
                    AND p_cursor_id IS NULL)
                OR (p_cursor_time IS NOT NULL
                    AND p_cursor_id > 0))
            AND CASE WHEN p_tab = 'current' THEN
                p_from IS NULL
                AND p_to IS NULL
                AND p_paid = 'all'
            ELSE
                p_from IS NOT NULL
                AND p_to IS NOT NULL
                AND p_to >= p_from
                AND p_to - p_from < 366
            END, FALSE) AS ok
),
filtered AS MATERIALIZED (
    SELECT
        d.*,
        CASE WHEN d.rider_payout::text NOT IN (
            'NaN', 'Infinity', '-Infinity'
) THEN
            round(
                d.rider_payout::numeric * 100
)::bigint
        END AS amount_minor
    FROM
        delivery_dispatch d,
        session s,
        valid v
    WHERE
        s.value ->> 'result' = 'ok'
        AND v.ok
        AND d.rider_id = s.value ->> 'rider_id'
        AND CASE WHEN p_tab = 'current' THEN
            d.status IN (
                'assigned', 'pickedup'
)
        ELSE
            d.status = 'completed'
            AND d.dtts >= ((
                    p_from::timestamp AT TIME ZONE 'Europe/London'
) AT TIME ZONE 'UTC'
)
            AND d.dtts < ((
                    (
                        p_to + 1
)::timestamp AT TIME ZONE 'Europe/London'
) AT TIME ZONE 'UTC'
)
            AND (
                p_paid = 'all'
                OR d.paid_status = p_paid
)
        END
),
page AS MATERIALIZED (
    SELECT
        *
    FROM
        filtered
    WHERE
        p_cursor_time IS NULL
        OR (
            dtts,
            dispatch_id
) < (
            p_cursor_time AT TIME ZONE 'UTC',
            p_cursor_id
)
    ORDER BY
        dtts DESC,
        dispatch_id DESC
    LIMIT p_limit + 1
),
shown AS MATERIALIZED (
    SELECT
        *
    FROM
        page
    ORDER BY
        dtts DESC,
        dispatch_id DESC
    LIMIT p_limit
),
projected AS (
    SELECT
        d.dtts,
        d.dispatch_id,
        jsonb_build_object('dispatch_id', d.dispatch_id, 'order_number', d.order_number, 'restaurant_name', s.rest_name, 'offered_at', d.dtts AT TIME ZONE 'UTC', 'order_placed_at', o.order_dtts, 'pickup_time', s.pickup_time, 'amount_minor', d.amount_minor, 'distance_km', d.distance, 'status', d.status, 'paid_status', CASE WHEN p_tab = 'completed' THEN
                d.paid_status
            END, 'marked_paid_at', CASE WHEN p_tab = 'completed'
                AND d.paid_status = 'paid' THEN
                d.paid_dtts AT TIME ZONE 'UTC'
            END) AS value
    FROM
        shown d
        LEFT JOIN delivery_summary s USING (order_number)
        LEFT JOIN LATERAL (
            SELECT
                min(order_dtts) AS order_dtts
            FROM
                food_order
            WHERE
                order_number = d.order_number) o ON TRUE
),
totals AS (
    SELECT
        CASE WHEN p_tab = 'current' THEN
            jsonb_build_object('count', count(*), 'expected_minor', coalesce(sum(amount_minor), 0))
        ELSE
            jsonb_build_object('count', count(*), 'earned_minor', coalesce(sum(amount_minor), 0), 'paid_minor', coalesce(sum(amount_minor) FILTER (WHERE paid_status = 'paid'), 0), 'unpaid_minor', coalesce(sum(amount_minor) FILTER (WHERE paid_status = 'unpaid'), 0))
        END AS value
    FROM
        filtered
)
SELECT
    CASE WHEN (
        SELECT
            value ->> 'result'
        FROM
            session) <> 'ok' THEN
        jsonb_build_object('result', 'invalid')
    WHEN NOT (
        SELECT
            ok
        FROM
            valid) THEN
        jsonb_build_object('result', 'bad_input')
    WHEN EXISTS (
        SELECT
            1
        FROM
            filtered
        WHERE
            rider_payout IS NULL
            OR rider_payout::text IN ('NaN', 'Infinity', '-Infinity')
            OR paid_status NOT IN ('paid', 'unpaid')
            OR paid_status IS NULL) THEN
        jsonb_build_object('result', 'bad_data')
    ELSE
        jsonb_build_object('result', 'ok', 'tab', p_tab, 'asOf', statement_timestamp(), 'rows', coalesce((
            SELECT
                jsonb_agg(value ORDER BY dtts DESC, dispatch_id DESC)
            FROM projected), '[]'::jsonb), 'summary', (
        SELECT
            value
        FROM totals), 'nextCursor', CASE WHEN (
        SELECT
            count(*)
    FROM page) > p_limit THEN
    (
        SELECT
            jsonb_build_object('time', dtts AT TIME ZONE 'UTC', 'id', dispatch_id)
    FROM shown ORDER BY dtts, dispatch_id LIMIT 1)
    ELSE
        NULL
    END)
    END;
$$;

-- get_rider_profile: authorize the cookie independently, then return only the rider's safe projection.
-- Returns result ok | invalid; bank_account_suffix is masked in SQL, never in the browser.
CREATE OR REPLACE FUNCTION public.get_rider_profile (p_cookie_hash text, p_ua_hash text)
    RETURNS jsonb
    LANGUAGE sql
    STABLE
    SET search_path = public, pg_temp
    AS $$
    WITH session AS (
        SELECT
            rider_dashboard_session (p_cookie_hash, p_ua_hash) AS value
)
    SELECT
        CASE WHEN value ->> 'result' <> 'ok' THEN
            jsonb_build_object('result', 'invalid')
        ELSE
            (
                SELECT
                    jsonb_build_object('result', 'ok', 'rider_name', r.rider_name, 'town', r.town, 'vehicle_type', r.vehicle_type, 'bank_account_suffix', CASE WHEN b.bank_account IS NOT NULL THEN
                            '•••• ' ||
                        RIGHT (b.bank_account, 4)
                        END)
                FROM
                    rider_master r
                LEFT JOIN LATERAL (
                    SELECT
                        bank_account
                    FROM
                        rider_registrations
                    WHERE
                        regexp_replace(phone, '[^0-9]', '', 'g') = r.rider_id
                    ORDER BY
                        updated_at DESC NULLS LAST
                    LIMIT 1) b ON TRUE
            WHERE
                r.rider_id = value ->> 'rider_id')
        END
    FROM
        session;
$$;

REVOKE ALL ON FUNCTION public.get_rider_jobs (text, text, text, date, date, text, timestamptz, integer, integer), public.get_rider_profile (text, text) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.get_rider_jobs (text, text, text, date, date, text, timestamptz, integer, integer), public.get_rider_profile (text, text) TO service_role;

COMMENT ON FUNCTION public.get_rider_jobs (text, text, text, date, date, text, timestamptz, integer, integer) IS 'Read only the authenticated rider jobs and full-filter earnings in one snapshot.';

COMMENT ON FUNCTION public.get_rider_profile (text, text) IS 'Read only the authenticated rider profile and server-masked account suffix.';
