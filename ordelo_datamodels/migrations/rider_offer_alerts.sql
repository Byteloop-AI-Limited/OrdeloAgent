-- MIGRATION (history; do not edit the statements below)
-- Applied to live: not yet (prepared 2026-10-26; the owner applies it by hand, nothing has been run).
-- Current definitions now live in: dispatch/rider_offer_alert.sql, dispatch/job_rider_offer_alerts.sql
-- Purpose: Telegram rider offer reminders. A job offer that a Telegram rider has not answered is sent again (fresh copy,
--          previous copy deleted) at RIDER_OFFER_ALERT_OFFSETS_SECS seconds after the offer ('10,20,30,45,60,90,120'),
--          until any rider of the order accepts, the order leaves 'unassigned', or the rider can no longer take it
--          (declined, paused, off shift, inactive, on another job, no Telegram chat). Overwatch is told once per order when
--          nobody has accepted by the last offset. Plan: plans/rider-dispatch-alerts-plan.md.
-- The feature files above are the current truth once the implementer creates them from this file; this file only records
-- the one-off change.

/*
HOW TO APPLY (Supabase SQL editor, one block at a time, in this order; no BEGIN/COMMIT):

  STEP 0  Run the PRE-CHECK query and read the result (all true; open_telegram_offers is informational).
  STEP 1  Run the TABLE block (rider_offer_alert, its indexes, RLS, REVOKE). Safe to re-run.
  STEP 2  Run the FUNCTIONS block (rider_offer_order_open, rider_offer_state, rider_offer_reminder_snapshot,
          rider_offer_reminder_sent, job_rider_offer_alerts) and the REVOKE lines. Safe to re-run (CREATE OR REPLACE).
  STEP 3  Run the CONFIG block (inserts RIDER_OFFER_ALERT_OFFSETS_SECS = '10,20,30,45,60,90,120' only if missing).
  STEP 4  Run the VERIFY query: 1 / true / 5 / 0 / '10,20,30,45,60,90,120'.
  STEP 5  Deploy the code (POST /rider-hooks/offer-alerts, ordelo/offer_reminders.py), then
          python scripts/datamodels/drift_check.py
  STEP 6  Schedule the job (operator step, after STEP 5):
            SELECT cron.schedule('job_rider_offer_alerts', '5 seconds', $$SELECT public.job_rider_offer_alerts()$$);
  STEP 7  Live test: ordelo_datamodels/test_support/test_restaurant_notices.sql STAGE 0, 1, (accept + pickup), 2b, 2c.

  Order matters only for STEP 6: the job POSTs to a route that exists only after STEP 5. Applying STEP 1-3 early is harmless
  (nothing calls the new objects until the job is scheduled). If the job is scheduled before the code is deployed, the POST
  answers 404, the job returns false and the checkpoints stay pending: nothing is lost, and only the latest due reminder per
  offer is sent once the route exists.

  OFF SWITCH: UPDATE public.ordelo_config SET config_value = '' WHERE config_key = 'RIDER_OFFER_ALERT_OFFSETS_SECS';
              (the next run cancels every pending reminder and seeds nothing). Or: SELECT cron.unschedule('job_rider_offer_alerts');

ROLLBACK (only if needed; each line stands alone):
  SELECT cron.unschedule('job_rider_offer_alerts');
  Redeploy the previous code. The table and functions are additive and unused by the previous code; leaving them is harmless.
  Optional, after the code no longer calls them:
    DROP FUNCTION IF EXISTS public.job_rider_offer_alerts();
    DROP FUNCTION IF EXISTS public.rider_offer_reminder_sent(integer, text, text);
    DROP FUNCTION IF EXISTS public.rider_offer_reminder_snapshot(integer);
    DROP FUNCTION IF EXISTS public.rider_offer_state(integer);
    DROP FUNCTION IF EXISTS public.rider_offer_order_open(text);
    DROP TABLE IF EXISTS public.rider_offer_alert;
    DELETE FROM public.ordelo_config WHERE config_key = 'RIDER_OFFER_ALERT_OFFSETS_SECS';   -- needs your explicit approval
*/

-- ===== PRE-CHECK (read only; expect true, true, true, true; open_telegram_offers is informational) =====
SELECT
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'delivery_dispatch' AND column_name = 'channel_msg_ref') AS dispatch_has_msg_ref,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'rider_master' AND column_name = 'tcid') AS rider_has_tcid,
    EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'is_paused') AS is_paused_present,
    EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'parse_alert_offsets') AS parse_alert_offsets_present,
    (SELECT count(*) FROM public.delivery_dispatch WHERE channel = 'telegram' AND status = 'unassigned'
        AND dtts > (now() - interval '15 minutes')::timestamp) AS open_telegram_offers;

-- ===== STEP 1: TABLE =====
-- One row per checkpoint. kind 'reminder': one Telegram offer (dispatch) at one offset. kind 'escalation': one order, to
-- overwatch, once. No foreign key to delivery_dispatch on purpose: dispatch_cancel_before_pickup() and the STRK test reset
-- DELETE dispatch rows; a reminder whose dispatch is gone is simply cancelled by the next run.
CREATE TABLE IF NOT EXISTS public.rider_offer_alert (
    id bigserial NOT NULL,
    kind text NOT NULL, -- 'reminder' (one rider's offer) | 'escalation' (the order, to overwatch, once)
    order_number text NOT NULL,
    dispatch_id integer, -- reminder: the offer (delivery_dispatch.dispatch_id); escalation: NULL
    rider_id text, -- reminder: delivery_dispatch.rider_id (for reading the ledger); escalation: NULL
    offset_secs integer NOT NULL, -- seconds after the offer (reminder) or after the order's first Telegram offer (escalation)
    n integer NOT NULL, -- 1-based position in the offset list ("reminder n of of_n"); escalation: 1
    of_n integer NOT NULL,
    due_at timestamp with time zone NOT NULL, -- delivery_dispatch.dtts + offset
    status text NOT NULL DEFAULT 'pending'::text,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    swept_at timestamp with time zone, -- when the job marked it sent / superseded / cancelled
    CONSTRAINT rider_offer_alert_pkey PRIMARY KEY (id),
    CONSTRAINT rider_offer_alert_kind_check CHECK ((kind = ANY (ARRAY['reminder'::text, 'escalation'::text]))),
    CONSTRAINT rider_offer_alert_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'sent'::text, 'superseded'::text, 'cancelled'::text]))),
    CONSTRAINT rider_offer_alert_shape_check CHECK (((kind = 'reminder'::text AND dispatch_id IS NOT NULL AND rider_id IS NOT NULL)
        OR (kind = 'escalation'::text AND dispatch_id IS NULL AND rider_id IS NULL)))
);

CREATE UNIQUE INDEX IF NOT EXISTS rider_offer_alert_reminder_uidx ON public.rider_offer_alert USING btree (dispatch_id, offset_secs)
WHERE (kind = 'reminder'::text);

CREATE UNIQUE INDEX IF NOT EXISTS rider_offer_alert_escalation_uidx ON public.rider_offer_alert USING btree (order_number)
WHERE (kind = 'escalation'::text);

CREATE INDEX IF NOT EXISTS rider_offer_alert_due ON public.rider_offer_alert USING btree (due_at)
WHERE (status = 'pending'::text);

ALTER TABLE public.rider_offer_alert ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.rider_offer_alert FROM PUBLIC, anon, authenticated;

REVOKE ALL ON SEQUENCE public.rider_offer_alert_id_seq FROM PUBLIC, anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.rider_offer_alert TO service_role;

GRANT USAGE, SELECT ON SEQUENCE public.rider_offer_alert_id_seq TO service_role;

COMMENT ON TABLE public.rider_offer_alert IS 'Telegram rider offer reminders (one row per offer and offset) and the once-per-order overwatch escalation.';

-- ===== STEP 2: FUNCTIONS =====

-- rider_offer_order_open(order_number) -> boolean
--   The ORDER-level stop rule (the owner's "stop once any rider accepts"): true while the order is still looking for a rider.
--   false as soon as any offer of the order is accepted / assigned / picked up / completed, a rider is inflight on it, or the
--   summary is no longer 'unassigned' (timed out, declined, completed, gone).
--   Why order-level: when an order is assigned, offers nobody answered keep status 'unassigned' (only accepted-but-lost offers
--   become 'missed', notify_missed_dispatches.sql), so an offer's own status cannot tell that the job is taken.
--   Data: reads delivery_summary, delivery_dispatch, delivery_inflight.
CREATE OR REPLACE FUNCTION public.rider_offer_order_open (p_order_number text)
    RETURNS boolean
    LANGUAGE sql
    STABLE
    SET search_path = public
    AS $$
    SELECT
        EXISTS (
            SELECT
                1
            FROM
                public.delivery_summary s
            WHERE
                s.order_number = p_order_number
                AND s.status = 'unassigned')
        AND NOT EXISTS (
            SELECT
                1
            FROM
                public.delivery_dispatch d
            WHERE
                d.order_number = p_order_number
                AND d.status IN ('accepted', 'assigned', 'pickedup', 'completed'))
        AND NOT EXISTS (
            SELECT
                1
            FROM
                public.delivery_inflight i
            WHERE
                i.order_number = p_order_number)
$$;

REVOKE ALL ON FUNCTION public.rider_offer_order_open (text) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.rider_offer_order_open (text) TO service_role;

COMMENT ON FUNCTION public.rider_offer_order_open (p_order_number text) IS 'True while a delivery order is still looking for a rider: summary unassigned, no offer accepted/assigned, nobody inflight.';

-- rider_offer_state(dispatch_id) -> jsonb {state, reason}
--   THE one place that says whether one Telegram offer may be reminded. Used by the job (seed / cancel), by the snapshot (check
--   BEFORE sending) and by reminder_sent (check AFTER sending).
--     state 'open'    remind it                                                         reason NULL
--     state 'quiet'   stop reminding; leave the rider's copy as it is (still tappable)  reason: accepted_elsewhere | not_telegram |
--                     no_rider | no_chat | inactive | off_shift | paused | on_another_job
--     state 'closed'  stop reminding; the copy should be redrawn without buttons         reason: an OfferClosedReason
--                     (ordelo/rider_messaging/models.py): gone | accepted | declined | taken | expired | assigned | cancelled
--   'accepted_elsewhere' is quiet, not closed: another rider tapped Accept but job_assign_dispatch() (5 s) has not picked the
--   winner yet; the assignment (close_open_offers 'taken', delivery_hooks.py) or the timeout ('expired') redraws the copy.
--   The rider-level rules mirror get_available_riders() (dispatch/job_create_dispatch.sql): status 'active', in shift,
--   not paused (is_paused('rider', rider_id, NULL)), not inflight on another job. Keep the two in step.
--   Data: reads delivery_dispatch, delivery_summary, delivery_inflight, rider_master; calls rider_offer_order_open(), is_paused().
CREATE OR REPLACE FUNCTION public.rider_offer_state (p_dispatch_id integer)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public
    AS $$
DECLARE
    v_order text;
    v_rider text;
    v_status text;
    v_channel text;
    v_summary text;
    v_rider_status text;
    v_in_shift boolean;
    v_tcid bigint;
BEGIN
    SELECT
        d.order_number::text,
        d.rider_id::text,
        d.status::text,
        d.channel INTO v_order,
        v_rider,
        v_status,
        v_channel
    FROM
        public.delivery_dispatch d
    WHERE
        d.dispatch_id = p_dispatch_id;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('state', 'closed', 'reason', 'gone');
    END IF;
    IF v_channel IS DISTINCT FROM 'telegram' THEN
        RETURN jsonb_build_object('state', 'quiet', 'reason', 'not_telegram');
    END IF;
    -- ---- this offer was answered or ended ----
    IF v_status <> 'unassigned' THEN
        RETURN jsonb_build_object('state', 'closed', 'reason', CASE v_status
            WHEN 'accepted' THEN 'accepted'
            WHEN 'declined' THEN 'declined'
            WHEN 'missed' THEN 'taken'
            WHEN 'timedout' THEN 'expired'
            WHEN 'assigned' THEN 'assigned'
            WHEN 'pickedup' THEN 'assigned'
            WHEN 'completed' THEN 'assigned'
            ELSE 'gone'
        END);
    END IF;
    -- ---- the order stopped looking for a rider ----
    IF NOT public.rider_offer_order_open (v_order) THEN
        SELECT
            s.status::text INTO v_summary
        FROM
            public.delivery_summary s
        WHERE
            s.order_number = v_order;
        IF v_summary IS NULL THEN
            RETURN jsonb_build_object('state', 'closed', 'reason', 'gone');
        ELSIF EXISTS (
            SELECT
                1
            FROM
                public.delivery_inflight i
            WHERE
                i.order_number = v_order) OR v_summary IN ('assigned', 'completed') THEN
            RETURN jsonb_build_object('state', 'closed', 'reason', 'taken');
        ELSIF v_summary = 'timedout' THEN
            RETURN jsonb_build_object('state', 'closed', 'reason', 'expired');
        ELSIF v_summary = 'declined' THEN
            RETURN jsonb_build_object('state', 'closed', 'reason', 'cancelled');
        ELSIF v_summary <> 'unassigned' THEN
            RETURN jsonb_build_object('state', 'closed', 'reason', 'gone');
        END IF;
        RETURN jsonb_build_object('state', 'quiet', 'reason', 'accepted_elsewhere');
    END IF;
    -- ---- this rider can no longer take it (same gate as get_available_riders) ----
    SELECT
        r.status::text,
        r.is_in_shift,
        r.tcid INTO v_rider_status,
        v_in_shift,
        v_tcid
    FROM
        public.rider_master r
    WHERE
        r.rider_id = v_rider;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('state', 'quiet', 'reason', 'no_rider');
    ELSIF v_tcid IS NULL THEN
        RETURN jsonb_build_object('state', 'quiet', 'reason', 'no_chat');
    ELSIF v_rider_status IS DISTINCT FROM 'active' THEN
        RETURN jsonb_build_object('state', 'quiet', 'reason', 'inactive');
    ELSIF v_in_shift IS NOT TRUE THEN
        RETURN jsonb_build_object('state', 'quiet', 'reason', 'off_shift');
    ELSIF public.is_paused ('rider', v_rider, NULL) THEN
        RETURN jsonb_build_object('state', 'quiet', 'reason', 'paused');
    ELSIF EXISTS (
        SELECT
            1
        FROM
            public.delivery_inflight i
        WHERE
            i.rider_id = v_rider) THEN
        RETURN jsonb_build_object('state', 'quiet', 'reason', 'on_another_job');
    END IF;
    RETURN jsonb_build_object('state', 'open', 'reason', NULL);
END
$$;

REVOKE ALL ON FUNCTION public.rider_offer_state (integer) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.rider_offer_state (integer) TO service_role;

COMMENT ON FUNCTION public.rider_offer_state (p_dispatch_id integer) IS 'Whether one Telegram offer may be reminded: {state open|quiet|closed, reason}. The one place the reminder stop rules live.';

-- rider_offer_reminder_snapshot(dispatch_id) -> jsonb
--   Everything needed to send one reminder, read in one call (the check BEFORE sending):
--     {state, reason, dispatch_id, order_number, rider_id, tcid, msg_ref,
--      offer: {dispatch_id, order_number, rider_id, rider_payout, vehicle_type, distance, pickup_time, rest_name, rest_address,
--              customer_name, customer_address} | null}
--   offer has the SAME keys and json types as one bulk_dispatch item of delivery_dispatch_whook_statement()
--   (dispatch/delivery_dispatch.sql), so ordelo/rider_messaging/offers.py job_offer() draws byte-identical text from either.
--   Data: reads delivery_dispatch, delivery_summary, rider_master; calls rider_offer_state().
--   Python: ordelo/offer_reminders.py SupabaseOfferReminderStore.snapshot().
CREATE OR REPLACE FUNCTION public.rider_offer_reminder_snapshot (p_dispatch_id integer)
    RETURNS jsonb
    LANGUAGE plpgsql
    STABLE
    SET search_path = public
    AS $$
DECLARE
    v_state jsonb;
    v_out jsonb;
BEGIN
    v_state := public.rider_offer_state (p_dispatch_id);
    SELECT
        jsonb_build_object('dispatch_id', d.dispatch_id, 'order_number', d.order_number, 'rider_id', d.rider_id, 'tcid', r.tcid, 'msg_ref', d.channel_msg_ref, 'offer', CASE WHEN s.order_number IS NULL THEN
                NULL
            ELSE
                jsonb_build_object('dispatch_id', d.dispatch_id, 'order_number', d.order_number, 'rider_id', d.rider_id, 'rider_payout', d.rider_payout, 'vehicle_type', d.vehicle_type, 'distance', d.distance, 'pickup_time', s.pickup_time, 'rest_name', s.rest_name, 'rest_address', s.rest_address, 'customer_name', s.customer_name, 'customer_address', s.customer_address)
            END) INTO v_out
    FROM
        public.delivery_dispatch d
    LEFT JOIN public.delivery_summary s ON s.order_number = d.order_number
    LEFT JOIN public.rider_master r ON r.rider_id = d.rider_id
WHERE
    d.dispatch_id = p_dispatch_id;
    RETURN v_state || COALESCE(v_out, jsonb_build_object('dispatch_id', p_dispatch_id, 'offer', NULL));
END
$$;

REVOKE ALL ON FUNCTION public.rider_offer_reminder_snapshot (integer) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.rider_offer_reminder_snapshot (integer) TO service_role;

COMMENT ON FUNCTION public.rider_offer_reminder_snapshot (p_dispatch_id integer) IS 'Everything needed to send one Telegram offer reminder (state, chat, current offer ref, offer facts) in one read.';

-- rider_offer_reminder_sent(dispatch_id, new_ref, expected_ref) -> jsonb
--   Called right AFTER the new copy was sent. Atomically moves delivery_dispatch.channel_msg_ref to the new copy, so every
--   later close (close_open_offers on assignment / timeout, the missed notice, a tap) edits the copy the rider actually sees.
--   Locks the dispatch row (FOR UPDATE) so two workers reminding the same offer cannot both win.
--     result 'swapped'  ref moved from expected_ref to new_ref; previous_ref = the copy to delete; plus {state, reason} AFTER
--                       the send (state 'closed' -> redraw the new copy with reason)
--     result 'stale'    channel_msg_ref is no longer expected_ref (another reminder won): delete the NEW copy; ref unchanged;
--                       current_ref = the copy that won
--     result 'gone'     the dispatch row no longer exists: redraw the new copy 'gone' and delete expected_ref
--   Data: reads/writes delivery_dispatch (channel_msg_ref); calls rider_offer_state().
--   Python: ordelo/offer_reminders.py SupabaseOfferReminderStore.reminder_sent().
CREATE OR REPLACE FUNCTION public.rider_offer_reminder_sent (p_dispatch_id integer, p_new_ref text, p_expected_ref text)
    RETURNS jsonb
    LANGUAGE plpgsql
    SET search_path = public
    AS $$
DECLARE
    v_ref text;
BEGIN
    SELECT
        d.channel_msg_ref INTO v_ref
    FROM
        public.delivery_dispatch d
    WHERE
        d.dispatch_id = p_dispatch_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('result', 'gone', 'previous_ref', p_expected_ref, 'state', 'closed', 'reason', 'gone');
    END IF;
    IF v_ref IS DISTINCT FROM p_expected_ref THEN
        RETURN jsonb_build_object('result', 'stale', 'current_ref', v_ref) || public.rider_offer_state (p_dispatch_id);
    END IF;
    UPDATE
        public.delivery_dispatch
    SET
        channel_msg_ref = p_new_ref
    WHERE
        dispatch_id = p_dispatch_id;
    RETURN jsonb_build_object('result', 'swapped', 'previous_ref', v_ref) || public.rider_offer_state (p_dispatch_id);
END
$$;

REVOKE ALL ON FUNCTION public.rider_offer_reminder_sent (integer, text, text) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.rider_offer_reminder_sent (integer, text, text) TO service_role;

COMMENT ON FUNCTION public.rider_offer_reminder_sent (p_dispatch_id integer, p_new_ref text, p_expected_ref text) IS 'After a reminder copy is sent: move channel_msg_ref to it if nobody else did (swapped | stale | gone) and return the offer state.';

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

-- ===== STEP 4: VERIFY (expect 1 / true / 5 / 0 / '10,20,30,45,60,90,120') =====
SELECT
    (SELECT count(*) FROM pg_class WHERE relname = 'rider_offer_alert' AND relkind = 'r') AS table_present,          -- 1
    (SELECT relrowsecurity FROM pg_class WHERE relname = 'rider_offer_alert' AND relkind = 'r') AS rls_on,             -- true
    (SELECT count(*) FROM pg_proc WHERE proname IN ('rider_offer_order_open', 'rider_offer_state', 'rider_offer_reminder_snapshot',
        'rider_offer_reminder_sent', 'job_rider_offer_alerts')) AS functions_present,                                  -- 5
    (SELECT count(*) FROM information_schema.role_routine_grants
      WHERE routine_name IN ('rider_offer_order_open', 'rider_offer_state', 'rider_offer_reminder_snapshot',
                             'rider_offer_reminder_sent', 'job_rider_offer_alerts')
        AND grantee IN ('anon', 'authenticated', 'PUBLIC')) AS public_grants,                                          -- 0
    (SELECT config_value FROM public.ordelo_config WHERE config_key = 'RIDER_OFFER_ALERT_OFFSETS_SECS') AS offsets;    -- '10,20,30,45,60,90,120'

-- ===== AFTER STEP 6 (read only): is it running? =====
-- SELECT jobname, schedule, active FROM cron.job WHERE jobname = 'job_rider_offer_alerts';
-- SELECT status, return_message, start_time FROM cron.job_run_details
--  WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'job_rider_offer_alerts') ORDER BY start_time DESC LIMIT 10;
-- SELECT kind, order_number, dispatch_id, offset_secs, n, of_n, due_at, status, swept_at FROM public.rider_offer_alert ORDER BY id DESC LIMIT 30;
