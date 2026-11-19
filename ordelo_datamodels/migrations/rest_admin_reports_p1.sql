-- MIGRATION (history; do not edit the statements below)
-- Applied to live: 2026-11-19 (agent, owner-authorised implementation run, during the owner's verification window)
-- Current definitions now live in: admin_dashboard/rest_admin_reports.sql
-- Purpose: restaurant dashboard operational report (owner decision O9', 19 Nov): order_milestone + first-decision capture
--          triggers on delivery_summary / takeaway_summary (AFTER UPDATE OF restaurant_confirmation_status; every error is
--          swallowed so an order update can never fail because of it) and rest_admin_report_operations().
-- VERIFY:  SELECT tgname FROM pg_trigger WHERE tgname LIKE '%_summary_milestones';  -- 2 rows
-- Then:    python scripts/datamodels/drift_check.py

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
