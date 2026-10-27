-- =============================================================================================
-- ordelo_datamodels/dispatch/rider_offer_alert.sql
-- Telegram rider offer reminders and the unanswered-order escalation.
-- =============================================================================================
-- LIVE CHECK    not yet applied to live; migration rider_offer_alerts.sql awaits owner execution.
-- OBJECTS       table  rider_offer_alert
--               fn     rider_offer_order_open, rider_offer_state, rider_offer_reminder_snapshot, rider_offer_reminder_sent
-- REQUIRES      dispatch/delivery_dispatch.sql, availability/pauses.sql
-- HOW TO RUN    Apply the migration first; this file maintains the definitions. Safe to re-run.
-- SIDE EFFECTS  Stores checkpoints and message references.
-- HOW IT FITS   Telegram only: delivery_dispatch.sql step 4 -> job_rider_offer_alerts -> rider-hooks/offer-alerts.
-- LIFECYCLE     pending -> sent, superseded or cancelled; one escalation per order.
-- CALLED BY     job_rider_offer_alerts(); ordelo/offer_reminders.py snapshot(), reminder_sent(), order_open()
-- PYTHON MODEL  ordelo/offer_reminders.py: SupabaseOfferReminderStore
-- SECURITY      RLS enabled; PUBLIC, anon and authenticated revoked; service role only.
-- TESTS         tests/sql/test_rider_offer_alerts_sql.py; tests/ordelo/test_offer_reminders.py
-- GOTCHAS       Rider gate mirrors get_available_riders(); dtts uses cron session time zone; no foreign key; accepted_elsewhere is quiet.
-- SEE ALSO      dispatch/delivery_dispatch.sql; plans/rider-dispatch-alerts-plan.md
-- =============================================================================================

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

