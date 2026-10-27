-- =============================================================================================
-- ordelo_datamodels/dispatch/job_rider_offer_alerts.sql
-- Telegram rider offer reminders and the unanswered-order escalation.
-- =============================================================================================
-- LIVE CHECK    not yet applied to live; migration rider_offer_alerts.sql awaits owner execution.
-- OBJECTS       fn     job_rider_offer_alerts() -> boolean
-- REQUIRES      dispatch/rider_offer_alert.sql; core/ordelo_config.sql
-- HOW TO RUN    Apply the migration first; this file maintains the definitions. Safe to re-run.
-- SIDE EFFECTS  Seeds and updates checkpoints; may POST reminders and escalations.
-- HOW IT FITS   Telegram only: delivery_dispatch.sql step 4 -> job_rider_offer_alerts -> rider-hooks/offer-alerts.
-- LIFECYCLE     pending -> sent, superseded or cancelled; one escalation per order.
-- CALLED BY     cron job_rider_offer_alerts, every 5 seconds
-- PYTHON MODEL  ordelo/offer_reminders.py: SupabaseOfferReminderStore
-- SECURITY      RLS enabled; PUBLIC, anon and authenticated revoked; service role only.
-- TESTS         tests/sql/test_rider_offer_alerts_sql.py; tests/ordelo/test_offer_reminders.py
-- GOTCHAS       One escalation per order even after re-dispatch; changes to offsets apply to new offers.
-- SEE ALSO      dispatch/delivery_dispatch.sql; plans/rider-dispatch-alerts-plan.md
-- =============================================================================================

-- job_rider_offer_alerts() -> boolean
--   Every 5 seconds (pg_cron 'job_rider_offer_alerts'). Structure follows telegram/t_order_alerts.sql job_t_order_alerts().
--     OFFSETS  parse_alert_offsets('RIDER_OFFER_ALERT_OFFSETS_SECS'), values <= 0 dropped (0 would repeat the offer itself).
--              NULL (blank / missing / unparseable) = OFF: every pending row is cancelled and nothing is seeded.
--     SEED     reminders: Telegram offers still 'unassigned', made in the last 15 minutes, whose rider_offer_state() is 'open'
--              -> one row per offset, due = dispatch dtts + offset.
--              escalation: each order with a Telegram offer in the last 15 minutes that is still open (rider_offer_order_open)
--              -> one row, due = first Telegram offer + the LAST offset (once per order, unique index).
--     CANCEL   pending reminders whose offer is no longer 'open'; pending escalations whose order is no longer open.
--     DUE      reminders: one winner per offer (largest due offset: after an outage only the latest is sent);
--              escalations: every due one, with how many Telegram offers / declines the order has.
--     POST     ORDELO_APP_URL/rider-hooks/offer-alerts {event_type, timestamp, reminders:[{dispatch_id, n, of}],
--              escalations:[{order_number, after_secs, offered, declined}]} -> watomation/routers/rider_offer_alerts.py
--     MARK     only on 2xx: due losers 'superseded' FIRST, then the due rows 'sent' (same order as job_t_order_alerts()).
--   Returns false when the POST failed (rows stay pending, retried next run), true otherwise.
--   delivery_dispatch.dtts is timestamp WITHOUT time zone written by job_create_dispatch() (a pg_cron session); this job is a
--   pg_cron session too, so dtts::timestamptz is read in the same time zone it was written in.
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
    -- ---- SEED reminders: one checkpoint per offset for each open Telegram offer -------------------------------
    INSERT INTO public.rider_offer_alert (kind, order_number, dispatch_id, rider_id, offset_secs, n, of_n, due_at)
    SELECT
        'reminder',
        d.order_number::text,
        d.dispatch_id,
        d.rider_id::text,
        off.v,
        off.n::int,
        cardinality(v_offsets),
        d.dtts::timestamptz + off.v * interval '1 second'
    FROM
        public.delivery_dispatch d
    CROSS JOIN LATERAL unnest(v_offsets)
    WITH ORDINALITY AS off (v, n)
WHERE
    d.channel = 'telegram'
        AND d.status = 'unassigned'
        AND d.dtts > (now() - interval '15 minutes')::timestamp
        AND (public.rider_offer_state (d.dispatch_id) ->> 'state') = 'open'
    ON CONFLICT (dispatch_id,
        offset_secs)
WHERE (kind = 'reminder')
    DO NOTHING;
    -- ---- SEED escalation: once per order, due after the order's first Telegram offer + the last offset --------
    INSERT INTO public.rider_offer_alert (kind, order_number, offset_secs, n, of_n, due_at)
    SELECT
        'escalation',
        d.order_number::text,
        v_last,
        1,
        1,
        min(d.dtts)::timestamptz + v_last * interval '1 second'
    FROM
        public.delivery_dispatch d
    WHERE
        d.channel = 'telegram'
        AND d.dtts > (now() - interval '15 minutes')::timestamp
        AND public.rider_offer_order_open (d.order_number::text)
    GROUP BY
        d.order_number
    ON CONFLICT (order_number)
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
            row_number() OVER (PARTITION BY a.dispatch_id ORDER BY a.offset_secs DESC) AS rn
        FROM
            public.rider_offer_alert a
        WHERE
            a.status = 'pending'
            AND a.kind = 'reminder'
            AND a.due_at <= now()) w
WHERE
    w.rn = 1;
    SELECT
        jsonb_agg(jsonb_build_object('order_number', a.order_number, 'after_secs', a.offset_secs, 'offered', (
                    SELECT
                        count(*)
                    FROM public.delivery_dispatch d
                    WHERE
                        d.order_number = a.order_number
                        AND d.channel = 'telegram'), 'declined', (
                    SELECT
                        count(*)
                    FROM public.delivery_dispatch d
                    WHERE
                        d.order_number = a.order_number
                        AND d.channel = 'telegram'
                        AND d.status = 'declined'))
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
            row_number() OVER (PARTITION BY x.dispatch_id ORDER BY x.offset_secs DESC) AS rn
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

COMMENT ON FUNCTION public.job_rider_offer_alerts () IS 'Every 5 seconds: seed, cancel, find due Telegram offer reminders and overwatch escalations, POST them, and mark them on success.';

-- ===== STEP 3: CONFIG (operator-editable; blank = reminders off) =====
INSERT INTO public.ordelo_config (config_key, config_value, description)
    VALUES ('RIDER_OFFER_ALERT_OFFSETS_SECS', '10,20,30,45,60,90,120', 'Seconds after a Telegram job offer at which an unanswered offer is sent again (fresh copy, previous copy deleted). Reminders stop when any rider of the order accepts. Overwatch is told once per order at the last offset if nobody accepted. Blank = off. Changes apply to new offers.')
ON CONFLICT (config_key)
    DO NOTHING;


-- Not yet active on live; owner schedules after deploying.
SELECT cron.schedule('job_rider_offer_alerts', '5 seconds', 'SELECT public.job_rider_offer_alerts()');
