-- ---------------------------------------------------------------------------
-- 002  payment_event: inbox + outcome log (no new payment_status values, ADR-0002)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.payment_event (
  id                 BIGSERIAL PRIMARY KEY,
  -- Stripe evt_…; 'authorised:<order_id>' for events without an id (/paid3100);
  -- 'ordelo:<kind>:<order_id>:…' for rows Ordelo writes itself.
  provider_event_id  TEXT NOT NULL,
  order_id           TEXT NOT NULL REFERENCES public.food_order(order_id) ON DELETE CASCADE,
  kind               TEXT NOT NULL CONSTRAINT payment_event_kind_chk CHECK (kind IN (
                        'authorised','authorised_duplicate','rejected_state',
                        'capture_requested','capture_succeeded','capture_failed',
                        'cancel_requested','cancel_succeeded','cancel_failed',
                        'refund_succeeded','init_reconcile_alerted')),
  payment_intent_id  TEXT NULL,
  amount_pence       INTEGER NULL,
  payload            JSONB NOT NULL DEFAULT '{}'::jsonb,   -- redacted; no customer data
  received_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT payment_event_provider_event_id_uq UNIQUE (provider_event_id)
);
CREATE INDEX IF NOT EXISTS payment_event_order_idx
  ON public.payment_event (order_id, received_at);
CREATE INDEX IF NOT EXISTS payment_event_kind_idx
  ON public.payment_event (kind, received_at);