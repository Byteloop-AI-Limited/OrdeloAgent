-- =============================================================================================
-- ordelo_datamodels/payment/payment_event.sql
-- Payment inbox and outcome log: one row per provider event or Ordelo-written payment fact, idempotent by event id.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  payment_event
--                   Append-only payment history per order_id (FK to food_order, ON DELETE CASCADE).
-- REQUIRES      restaurant-agents: food_order
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   Writers:
--                   record_payment_authorised()      'authorised' / 'authorised_duplicate' / 'rejected_state' (payment callback)
--                   job_payment_init_reconciler()    'init_reconcile_alerted' (paid order with no fulfilment row)
--                   utils_common/payment_ms/payment_events.py, utils_common/web_ordering/lifecycle.py   capture / cancel / refund facts
--                 provider_event_id is unique: Stripe 'evt_...', 'authorised:<order_id>' for id-less callbacks (/paid3100), or
--                 'ordelo:<kind>:<order_id>:...' for rows Ordelo writes itself, so every writer is naturally idempotent.
--                 No new food_order.payment_status values are introduced (ADR-0002): the status stays on food_order, the history here.
-- LIFECYCLE     append-only; kind says what happened.
-- CALLED BY     payment_event:
--                 sql       job_payment_init_reconciler(), record_payment_authorised()
--                 python    utils_common/payment_ms/payment_events.py (module-level SQL)
--                 python    utils_common/web_ordering/lifecycle.py: reject_late()
-- PYTHON MODEL  none
-- SECURITY      payment_event: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         tests/utils_common/web_ordering/test_web_contract.py
-- GOTCHAS       payload is redacted: no customer data.
-- SEE ALSO      payment/record_payment_authorised.sql
--               payment/job_payment_init_reconciler.sql
--               docs/payment_and_order_flow.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table payment_event
--   Append-only payment history per order_id (FK to food_order, ON DELETE CASCADE).
--   kind: authorised | authorised_duplicate | rejected_state | capture_requested | capture_succeeded | capture_failed |
--         cancel_requested | cancel_succeeded | cancel_failed | refund_succeeded | init_reconcile_alerted
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.payment_event IS 'Append-only payment history per order_id (FK to food_order, ON DELETE CASCADE).';
