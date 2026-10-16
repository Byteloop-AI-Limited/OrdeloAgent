-- ===========================================================================
-- 1. THE LEDGER
--    One row per checkpoint. Answers "what was sent, what is still to come".
-- ===========================================================================
CREATE TABLE IF NOT EXISTS public.rider_pickup_alert (
    dispatch_id integer NOT NULL,
    phase character varying(20) NOT NULL,
    audience character varying(20) NOT NULL,
    offset_minutes integer NOT NULL,
    order_number character varying(100) NOT NULL,
    rider_id character varying(12) NOT NULL,
    status character varying(20) NOT NULL DEFAULT 'pending' ::character varying,
    due_dtts timestamp with time zone NOT NULL,
    sent_dtts timestamp with time zone,
    dt date NOT NULL DEFAULT CURRENT_DATE,
    dtts timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT rider_pickup_alert_pkey PRIMARY KEY (dispatch_id, phase, audience, offset_minutes),
    CONSTRAINT rider_pickup_alert_audience_check CHECK (((audience)::text = ANY ((ARRAY['rider'::character varying, 'ops'::character varying, 'rest_admins'::character varying])::text[]))),
    CONSTRAINT rider_pickup_alert_phase_check CHECK (((phase)::text = ANY ((ARRAY['awaiting_pickup'::character varying, 'picked_up'::character varying])::text[]))),
    CONSTRAINT rider_pickup_alert_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'sent'::character varying, 'superseded'::character varying])::text[]))),
    CONSTRAINT rider_pickup_alert_dispatch_id_fkey FOREIGN KEY (dispatch_id) REFERENCES delivery_dispatch (dispatch_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS rider_pickup_alert_due_idx ON public.rider_pickup_alert USING btree (status, due_dtts);

CREATE INDEX IF NOT EXISTS rider_pickup_alert_order_idx ON public.rider_pickup_alert USING btree (order_number);
