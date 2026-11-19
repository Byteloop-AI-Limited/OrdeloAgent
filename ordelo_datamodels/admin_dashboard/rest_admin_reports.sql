-- =============================================================================================
-- ordelo_datamodels/admin_dashboard/rest_admin_reports.sql
-- Restaurant dashboard operational report: how fast orders are accepted and how pickups compare with their promise.
-- =============================================================================================
-- LIVE CHECK    New in plans/telegram-portal-links-and-dashboard-plan.md (O9', owner decision 19 Nov 2026); applied with
--               migrations/rest_admin_reports_p1.sql. order_milestone capture starts on the day it is applied (no backfill).
-- OBJECTS       table  order_milestone
--                   First-occurrence facts of an order that later updates would otherwise overwrite (restaurant decision).
--               fn     order_milestone_capture() -> trigger
--                   Stamps the restaurant's first decision on delivery_summary / takeaway_summary; never fails the update.
--               trigger delivery_summary_milestones, takeaway_summary_milestones
--                   AFTER UPDATE OF restaurant_confirmation_status on the two summary tables.
--               fn     rest_admin_report_operations(p_session_id uuid, p_from date, p_to date, p_kind text) -> jsonb
--                   Acceptance and pickup measures for the signed-in admin's restaurant over London creation dates.
-- REQUIRES      delivery/delivery_summary.sql, takeaway/takeaway_summary.sql
--               notifications/order_customer_event.sql (food_collected: the verified collection fact)
--               ordering/order_has_test_item.sql (test orders are left out)
--               admin_dashboard/auth_sessions.sql (rest_admin_session_actor)
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
-- SIDE EFFECTS  Creates the empty table order_milestone and two AFTER UPDATE triggers.
-- HOW IT FITS   Cohort: an order belongs to the London date of its summary row's dtts (creation). Test orders (TEST3100) are
--                 excluded. Measures (owner decision 19 Nov):
--                 acceptance   manual (restaurant_accept / restaurant_pickuptime_adjusted, not configured_auto),
--                              configured auto-accept (rest_confirmation_method = 'configured_auto'), timeout fallback
--                              (auto_accept without that method), declined (restaurant_decline / auto_decline), no answer
--                              (restaurant_timedout / unconfirmed). Manual acceptance minutes = first decision time - dtts,
--                              where the first decision time is order_milestone 'decided' (captured from this file's
--                              apply date) or, for older orders still in plain restaurant_accept, restaurant_update_dtts.
--                 pickup       delivery only: food_collected (order_customer_event, not an estimate) - dtts; and minutes
--                              early (-) or late (+) against the ORIGINAL promise (coalesce(pickup_time_initial, pickup_time))
--                              and the LATEST promise in force at collection (pickup_time). E.g. collected 18:45, original
--                              18:30, latest 18:50 -> +15 and -5. Medians are over orders; each measure reports its sample.
-- LIFECYCLE     RESULT VOCABULARY: ok | bad_range (to < from, or more than 366 days) | not_authorised
-- CALLED BY     rest_admin_report_operations:
--                 frontend  restaurant-frontend/lib/rest-admin-rpc.ts (app/api/rest-admin/reports/operations/route.ts)
--               order_milestone_capture:
--                 sql       triggers delivery_summary_milestones, takeaway_summary_milestones
-- PYTHON MODEL  none
-- SECURITY      Table: RLS on, no policies, REVOKE ALL FROM anon, authenticated. The report: REVOKE ALL FROM PUBLIC, anon,
--               authenticated; granted to service_role. The trigger function runs as the updating role.
-- TESTS         tests/sql/test_rest_admin_reports_sql.py
-- GOTCHAS       The capture trigger swallows every error (it must never block an order update); a missing milestone only
--                 lowers the report's measured sample. Coverage before the apply date comes from restaurant_update_dtts and
--                 only for orders never adjusted afterwards.
-- SEE ALSO      admin_dashboard/v_admin_orders.sql (the financial views), plans/telegram-portals-and-restaurant-dashboard.md
-- =============================================================================================

CREATE TABLE IF NOT EXISTS public.order_milestone (
    order_number text NOT NULL,
    milestone text NOT NULL,            -- decided
    at timestamptz NOT NULL,
    data jsonb,                         -- {"status": <restaurant_confirmation_status>, "kind": "delivery" | "takeaway"}
    CONSTRAINT order_milestone_pkey PRIMARY KEY (order_number, milestone)
);
ALTER TABLE public.order_milestone ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.order_milestone FROM anon, authenticated;
GRANT ALL ON TABLE public.order_milestone TO service_role;

CREATE OR REPLACE FUNCTION public.order_milestone_capture ()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    SET search_path = public, pg_temp
    AS $$
BEGIN
    BEGIN
        IF OLD.restaurant_confirmation_status IS DISTINCT FROM NEW.restaurant_confirmation_status
            AND OLD.restaurant_confirmation_status = 'restaurant_unconfirmed'
            AND NEW.restaurant_confirmation_status IN ('restaurant_accept', 'restaurant_pickuptime_adjusted', 'restaurant_decline') THEN
            INSERT INTO order_milestone (order_number, milestone, at, data)
                VALUES (NEW.order_number, 'decided', clock_timestamp(),
                        jsonb_build_object('status', NEW.restaurant_confirmation_status, 'kind', TG_ARGV[0]))
            ON CONFLICT (order_number, milestone) DO NOTHING;
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            NULL;  -- reporting must never block an order update
    END;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS delivery_summary_milestones ON public.delivery_summary;
CREATE TRIGGER delivery_summary_milestones
    AFTER UPDATE OF restaurant_confirmation_status ON public.delivery_summary
    FOR EACH ROW EXECUTE FUNCTION order_milestone_capture ('delivery');

DROP TRIGGER IF EXISTS takeaway_summary_milestones ON public.takeaway_summary;
CREATE TRIGGER takeaway_summary_milestones
    AFTER UPDATE OF restaurant_confirmation_status ON public.takeaway_summary
    FOR EACH ROW EXECUTE FUNCTION order_milestone_capture ('takeaway');

CREATE OR REPLACE FUNCTION public.rest_admin_report_operations (p_session_id uuid, p_from date, p_to date, p_kind text)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public, pg_temp
    AS $$
DECLARE
    a record;
    v_kind text := CASE WHEN p_kind IN ('delivery', 'takeaway') THEN p_kind ELSE 'all' END;
    v_out jsonb;
BEGIN
    SELECT * INTO a FROM rest_admin_session_actor (p_session_id);
    IF p_from IS NULL OR p_to IS NULL OR p_to < p_from OR p_to - p_from > 366 THEN
        RETURN jsonb_build_object('result', 'bad_range');
    END IF;
    WITH orders AS (
        SELECT 'delivery'::text AS kind, s.order_number, s.dtts, s.restaurant_confirmation_status AS rcs,
               s.rest_confirmation_method AS method, s.restaurant_update_dtts AS decided_fallback,
               coalesce(s.pickup_time_initial, s.pickup_time) AS promise_original, s.pickup_time AS promise_latest
        FROM delivery_summary s
        WHERE upper(s.rest_ref) = a.rest_ref AND v_kind IN ('all', 'delivery')
        UNION ALL
        SELECT 'takeaway', t.order_number, t.dtts, t.restaurant_confirmation_status, t.rest_confirmation_method,
               t.restaurant_update_dtts, t.pickup_time, t.pickup_time
        FROM takeaway_summary t
        WHERE upper(t.rest_ref) = a.rest_ref AND v_kind IN ('all', 'takeaway')
    ), cohort AS (
        SELECT o.*, (o.dtts AT TIME ZONE 'Europe/London')::date AS day,
               CASE WHEN o.method = 'configured_auto' THEN 'configured_auto'
                    WHEN o.rcs IN ('restaurant_accept', 'restaurant_pickuptime_adjusted') THEN 'manual'
                    WHEN o.rcs = 'auto_accept' THEN 'timeout_auto'
                    WHEN o.rcs IN ('restaurant_decline', 'auto_decline') THEN 'declined'
                    ELSE 'no_answer' END AS decision
        FROM orders o
        WHERE (o.dtts AT TIME ZONE 'Europe/London')::date BETWEEN p_from AND p_to
          AND NOT coalesce(order_has_test_item (o.order_number), FALSE)
    ), measured AS (
        SELECT c.*,
               CASE WHEN c.decision = 'manual' THEN
                   extract(epoch FROM coalesce(m.at, CASE WHEN c.rcs = 'restaurant_accept' THEN c.decided_fallback END) - c.dtts) / 60.0
               END AS accept_min,
               CASE WHEN c.kind = 'delivery' THEN extract(epoch FROM e.occurred_at - c.dtts) / 60.0 END AS to_pickup_min,
               CASE WHEN c.kind = 'delivery' THEN extract(epoch FROM e.occurred_at - c.promise_original) / 60.0 END AS vs_original_min,
               CASE WHEN c.kind = 'delivery' THEN extract(epoch FROM e.occurred_at - c.promise_latest) / 60.0 END AS vs_latest_min
        FROM cohort c
        LEFT JOIN order_milestone m ON m.order_number = c.order_number AND m.milestone = 'decided'
        LEFT JOIN order_customer_event e ON e.order_number = c.order_number AND e.event_key = 'food_collected' AND NOT e.is_estimate
    ), clean AS (
        SELECT m.*, CASE WHEN m.accept_min >= 0 THEN m.accept_min END AS accept_ok,
               CASE WHEN m.to_pickup_min >= 0 THEN m.to_pickup_min END AS pickup_ok
        FROM measured m
    )
    SELECT jsonb_build_object(
        'result', 'ok', 'rest_ref', a.rest_ref, 'from', p_from, 'to', p_to, 'kind', v_kind, 'timezone', 'Europe/London',
        'totals', (SELECT jsonb_build_object(
            'orders', count(*),
            'manual', count(*) FILTER (WHERE decision = 'manual'),
            'configured_auto', count(*) FILTER (WHERE decision = 'configured_auto'),
            'timeout_auto', count(*) FILTER (WHERE decision = 'timeout_auto'),
            'declined', count(*) FILTER (WHERE decision = 'declined'),
            'no_answer', count(*) FILTER (WHERE decision = 'no_answer'),
            'accept_measured', count(accept_ok),
            'accept_median_min', round((percentile_cont(0.5) WITHIN GROUP (ORDER BY accept_ok))::numeric, 1),
            'deliveries', count(*) FILTER (WHERE kind = 'delivery'),
            'pickup_measured', count(pickup_ok),
            'to_pickup_median_min', round((percentile_cont(0.5) WITHIN GROUP (ORDER BY pickup_ok))::numeric, 1),
            'vs_original_median_min', round((percentile_cont(0.5) WITHIN GROUP (ORDER BY vs_original_min) FILTER (WHERE pickup_ok IS NOT NULL))::numeric, 1),
            'vs_latest_median_min', round((percentile_cont(0.5) WITHIN GROUP (ORDER BY vs_latest_min) FILTER (WHERE pickup_ok IS NOT NULL))::numeric, 1),
            'late_vs_original', count(*) FILTER (WHERE pickup_ok IS NOT NULL AND vs_original_min > 0),
            'late_vs_latest', count(*) FILTER (WHERE pickup_ok IS NOT NULL AND vs_latest_min > 0))
            FROM clean),
        'days', (SELECT coalesce(jsonb_agg(d ORDER BY d ->> 'day'), '[]'::jsonb) FROM (
            SELECT jsonb_build_object(
                'day', day, 'orders', count(*),
                'manual', count(*) FILTER (WHERE decision = 'manual'),
                'auto', count(*) FILTER (WHERE decision IN ('configured_auto', 'timeout_auto')),
                'timeout_auto', count(*) FILTER (WHERE decision = 'timeout_auto'),
                'declined', count(*) FILTER (WHERE decision = 'declined'),
                'accept_measured', count(accept_ok),
                'accept_median_min', round((percentile_cont(0.5) WITHIN GROUP (ORDER BY accept_ok))::numeric, 1),
                'pickup_measured', count(pickup_ok),
                'to_pickup_median_min', round((percentile_cont(0.5) WITHIN GROUP (ORDER BY pickup_ok))::numeric, 1),
                'vs_original_median_min', round((percentile_cont(0.5) WITHIN GROUP (ORDER BY vs_original_min) FILTER (WHERE pickup_ok IS NOT NULL))::numeric, 1),
                'vs_latest_median_min', round((percentile_cont(0.5) WITHIN GROUP (ORDER BY vs_latest_min) FILTER (WHERE pickup_ok IS NOT NULL))::numeric, 1)) AS d
            FROM clean GROUP BY day) x))
    INTO v_out;
    RETURN v_out;
EXCEPTION
    WHEN invalid_authorization_specification THEN
        RETURN jsonb_build_object('result', 'not_authorised');
END;
$$;

-- order_milestone_capture() is a trigger function (it cannot be called directly) and keeps its default EXECUTE.
REVOKE ALL ON FUNCTION public.rest_admin_report_operations (uuid, date, date, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.rest_admin_report_operations (uuid, date, date, text) TO service_role;
