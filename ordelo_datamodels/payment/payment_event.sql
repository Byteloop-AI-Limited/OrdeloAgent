-- ---------------------------------------------------------------------------
-- 002  payment_event: inbox + outcome log (no new payment_status values, ADR-0002)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.payment_event (
    id bigserial NOT NULL,
    -- Stripe evt_…; 'authorised:<order_id>' for events without an id (/paid3100);
    -- 'ordelo:<kind>:<order_id>:…' for rows Ordelo writes itself.
    provider_event_id text NOT NULL,
    order_id text NOT NULL,
    kind text NOT NULL,
    payment_intent_id text,
    amount_pence integer,
    payload jsonb NOT NULL DEFAULT '{}' ::jsonb, -- redacted; no customer data
    received_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT payment_event_pkey PRIMARY KEY (id),
    CONSTRAINT payment_event_provider_event_id_uq UNIQUE (provider_event_id),
    CONSTRAINT payment_event_kind_chk CHECK ((kind = ANY (ARRAY['authorised'::text, 'authorised_duplicate'::text, 'rejected_state'::text, 'capture_requested'::text, 'capture_succeeded'::text, 'capture_failed'::text, 'cancel_requested'::text, 'cancel_succeeded'::text, 'cancel_failed'::text, 'refund_succeeded'::text, 'init_reconcile_alerted'::text]))),
    CONSTRAINT payment_event_order_id_fkey FOREIGN KEY (order_id) REFERENCES food_order (order_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS payment_event_kind_idx ON public.payment_event USING btree (kind, received_at);

CREATE INDEX IF NOT EXISTS payment_event_order_idx ON public.payment_event USING btree (order_id, received_at);
