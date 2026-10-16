-- MIGRATION (history; do not edit the statements below)
-- Applied to live: Applied, except the pg_cron schedule for job_payment_init_reconciler (not in cron.job; docs/to-do.md).
-- Current definitions now live in: notifications/notification_outbox.sql
--               notifications/order_customer_event.sql
--               notifications/order_notification_subscription.sql
--               ordering/create_food_order_with_items.sql
--               ordering/food_order_additions.sql
--               payment/job_payment_init_reconciler.sql
--               payment/payment_event.sql
--               payment/record_payment_authorised.sql
--               restaurant-agents (food_order)
-- Purpose: Web ordering R1: food_order columns, payment inbox, order-creation RPC, reconciler, notification tables.
-- The feature files above are the current truth; this file only records the one-off change.

-- ===========================================================================
-- ordelo-agg R1 migrations (R1a + R1b)            plans/ordelo-agg-plan-cc.md
-- ===========================================================================
-- Run manually, top to bottom, in one session (D31). Every statement is
-- idempotent and additive, so re-running the file is safe.
--
--   001  food_order: origin_channel, storefront, idempotency_key      (R1a)
--   002  payment_event inbox / outcome log                             (R1a)
--   R1a  RPC create_food_order_with_items      (F4, flag ORDER_CREATE_RPC_ENABLED)
--   R1a  RPC record_payment_authorised         (M2, flag PAYMENT_INBOX_ENABLED)
--   R1a  job_payment_init_reconciler           (alert-only init reconciler)
--   003  subscriptions, customer events, outbox                        (R1b)
--
-- Nothing here changes behaviour on its own: the application only uses the
-- RPCs once the matching ordelo_config flag is set (section 4), and the
-- reconciler only runs once it is scheduled and PAYMENT_INIT_RECONCILER_SINCE
-- is set.
--
-- Before running: confirm no order is mid-fulfilment (plan §18 R1a):
--   SELECT order_number FROM delivery_summary WHERE status NOT IN ('completed','timedout')
--   UNION ALL
--   SELECT order_number FROM takeaway_summary WHERE status NOT IN ('completed','declined')
--   UNION ALL
--   SELECT order_number FROM food_order
--    WHERE payment_status = 'requires_payment' AND order_dt = CURRENT_DATE;
-- ===========================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 001  food_order: origin channel, storefront, idempotency key   (D15, D28)
-- ---------------------------------------------------------------------------
ALTER TABLE public.food_order
  ADD COLUMN IF NOT EXISTS origin_channel TEXT NOT NULL DEFAULT 'whatsapp'
      CONSTRAINT food_order_origin_channel_chk CHECK (origin_channel IN ('whatsapp','web')),
  ADD COLUMN IF NOT EXISTS storefront TEXT NOT NULL DEFAULT 'direct'
      CONSTRAINT food_order_storefront_chk CHECK (storefront IN ('direct','ordelo')),
  ADD COLUMN IF NOT EXISTS payment_mode TEXT NULL CHECK (payment_mode IN ('live','test')),
  ADD COLUMN IF NOT EXISTS idempotency_key TEXT NULL;   -- used by web create-order (R3)

CREATE UNIQUE INDEX IF NOT EXISTS food_order_idempotency_key_uq
  ON public.food_order (idempotency_key) WHERE idempotency_key IS NOT NULL;

-- origin_channel and storefront are written once at insert and never change.
CREATE OR REPLACE FUNCTION public.forbid_food_order_origin_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.origin_channel IS DISTINCT FROM OLD.origin_channel THEN
    RAISE EXCEPTION 'food_order.origin_channel is immutable (order %)', OLD.order_number;
  END IF;
  IF NEW.storefront IS DISTINCT FROM OLD.storefront THEN
    RAISE EXCEPTION 'food_order.storefront is immutable (order %)', OLD.order_number;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS food_order_origin_immutable ON public.food_order;
CREATE TRIGGER food_order_origin_immutable
  BEFORE UPDATE OF origin_channel, storefront ON public.food_order
  FOR EACH ROW EXECUTE FUNCTION public.forbid_food_order_origin_change();


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


-- ---------------------------------------------------------------------------
-- R1a  F4: create the order and its items in one transaction
-- ---------------------------------------------------------------------------
-- p_order: {order_id, order_number, seq_id, recipient, notes, thread_id, action,
--           total_price, payment_status?, origin_channel?, storefront?}
-- p_items: [{product_name, sku, quantity, price, modifications?}, …]
-- Any failure (including a duplicate order_id) raises and rolls back both inserts.
CREATE OR REPLACE FUNCTION public.create_food_order_with_items(p_order jsonb, p_items jsonb)
RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
  v_order  jsonb;
  v_items  integer;
BEGIN
  IF p_items IS NULL OR jsonb_typeof(p_items) <> 'array' OR jsonb_array_length(p_items) = 0 THEN
    RAISE EXCEPTION 'create_food_order_with_items: p_items must be a non-empty array';
  END IF;

  INSERT INTO public.food_order (
    order_id, order_number, seq_id, recipient, notes, thread_id, action,
    total_price, payment_status, origin_channel, storefront, payment_mode, idempotency_key)
  VALUES (
    p_order->>'order_id',
    p_order->>'order_number',
    (p_order->>'seq_id')::integer,
    p_order->>'recipient',
    p_order->>'notes',
    p_order->>'thread_id',
    p_order->>'action',
    (p_order->>'total_price')::double precision,
    COALESCE(p_order->>'payment_status', 'requires_payment'),
    COALESCE(p_order->>'origin_channel', 'whatsapp'),
    COALESCE(p_order->>'storefront', 'direct'),
    CASE WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(p_items) x
                      WHERE x->>'product_name' = 'TEST3100')
         THEN 'test' ELSE 'live' END,
    NULLIF(p_order->>'idempotency_key', ''))
  RETURNING to_jsonb(food_order.*) INTO v_order;

  INSERT INTO public.order_item (order_id, product_name, sku, quantity, price, modifications)
  SELECT p_order->>'order_id',
         x->>'product_name',
         x->>'sku',
         (x->>'quantity')::integer,
         (x->>'price')::double precision,
         CASE WHEN jsonb_typeof(x->'modifications') = 'array'
              THEN ARRAY(SELECT jsonb_array_elements_text(x->'modifications'))
              ELSE NULL END
    FROM jsonb_array_elements(p_items) AS x;
  GET DIAGNOSTICS v_items = ROW_COUNT;

  RETURN jsonb_build_object('order', v_order, 'item_count', v_items);
END $$;


-- ---------------------------------------------------------------------------
-- R1a  M2: apply a payment authorisation at most once
-- ---------------------------------------------------------------------------
-- Returns {"outcome": "applied", "order": {...food_order row...}}
--      or {"outcome": "duplicate"}                (same event seen before)
--      or {"outcome": "rejected_state", "payment_status": "..."}  (not requires_payment)
--      or {"outcome": "unknown_order"}            (no such order_id)
CREATE OR REPLACE FUNCTION public.record_payment_authorised(
  p_provider_event_id text,
  p_order_id          text,
  p_payment_intent_id text DEFAULT NULL,
  p_amount_pence      integer DEFAULT NULL,
  p_payload           jsonb DEFAULT '{}'::jsonb)
RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
  v_order   public.food_order%ROWTYPE;
  v_status  text;
  v_new_id  bigint;
BEGIN
  IF p_provider_event_id IS NULL OR p_order_id IS NULL THEN
    RAISE EXCEPTION 'record_payment_authorised: event id and order id are required';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM public.food_order WHERE order_id = p_order_id) THEN
    RETURN jsonb_build_object('outcome', 'unknown_order');
  END IF;

  INSERT INTO public.payment_event
         (provider_event_id, order_id, kind, payment_intent_id, amount_pence, payload)
  VALUES (p_provider_event_id, p_order_id, 'authorised', p_payment_intent_id,
          p_amount_pence, COALESCE(p_payload, '{}'::jsonb))
  ON CONFLICT (provider_event_id) DO NOTHING
  RETURNING id INTO v_new_id;

  IF v_new_id IS NULL THEN
    INSERT INTO public.payment_event (provider_event_id, order_id, kind, payload)
    VALUES ('ordelo:authorised_duplicate:' || p_order_id || ':' || gen_random_uuid(),
            p_order_id, 'authorised_duplicate',
            jsonb_build_object('original_event_id', p_provider_event_id));
    RETURN jsonb_build_object('outcome', 'duplicate');
  END IF;

  UPDATE public.food_order
     SET payment_status = 'requires_capture'
   WHERE order_id = p_order_id
     AND payment_status = 'requires_payment'
  RETURNING * INTO v_order;

  IF NOT FOUND THEN
    SELECT payment_status INTO v_status FROM public.food_order WHERE order_id = p_order_id;
    UPDATE public.payment_event SET kind = 'rejected_state' WHERE id = v_new_id;
    RETURN jsonb_build_object('outcome', 'rejected_state', 'payment_status', v_status);
  END IF;

  RETURN jsonb_build_object('outcome', 'applied', 'order', to_jsonb(v_order));
END $$;


-- ---------------------------------------------------------------------------
-- R1a  Init reconciler (alert-only): paid orders with no fulfilment summary
-- ---------------------------------------------------------------------------
-- Disabled until ordelo_config.PAYMENT_INIT_RECONCILER_SINCE holds a timestamp;
-- only orders created after it are checked. Each order is alerted once
-- (payment_event kind 'init_reconcile_alerted'). Posts to
-- {ORDELO_APP_URL}/payment-hooks/init-reconciler, which alerts overwatch.
CREATE OR REPLACE FUNCTION public.job_payment_init_reconciler()
RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
  v_since    timestamptz;
  v_app_url  text;
  v_orders   jsonb;
  v_count    integer;
  v_resp     http_response;
BEGIN
  SELECT NULLIF(config_value, '')::timestamptz INTO v_since
    FROM public.ordelo_config WHERE config_key = 'PAYMENT_INIT_RECONCILER_SINCE';
  IF v_since IS NULL THEN
    RETURN 0;
  END IF;

  WITH stuck AS (
    SELECT fo.order_id, fo.order_number, fo.action,
           COALESCE((SELECT max(pe.received_at) FROM public.payment_event pe
                      WHERE pe.order_id = fo.order_id AND pe.kind = 'authorised'),
                    fo.order_dtts) AS authorised_at
      FROM public.food_order fo
     WHERE fo.payment_status = 'requires_capture'
       AND fo.order_dtts >= v_since
       AND NOT EXISTS (SELECT 1 FROM public.payment_event pe
                        WHERE pe.order_id = fo.order_id AND pe.kind = 'init_reconcile_alerted')
       AND NOT (fo.action = 'delivery'
                AND EXISTS (SELECT 1 FROM public.delivery_summary ds WHERE ds.order_number = fo.order_number))
       AND NOT (fo.action = 'takeaway'
                AND EXISTS (SELECT 1 FROM public.takeaway_summary ts WHERE ts.order_number = fo.order_number))
  )
  SELECT jsonb_agg(jsonb_build_object('order_id', order_id, 'order_number', order_number,
                                      'action', action, 'authorised_at', authorised_at)),
         count(*)
    INTO v_orders, v_count
    FROM stuck
   WHERE authorised_at < now() - interval '2 minutes';

  IF COALESCE(v_count, 0) = 0 THEN
    RETURN 0;
  END IF;

  SELECT config_value INTO v_app_url FROM public.ordelo_config WHERE config_key = 'ORDELO_APP_URL';
  IF v_app_url IS NULL OR length(v_app_url) = 0 THEN
    v_app_url := 'https://agent.ordelo.app';
  END IF;
  IF right(v_app_url, 1) = '/' THEN
    v_app_url := left(v_app_url, length(v_app_url) - 1);
  END IF;

  SELECT * INTO v_resp
    FROM http_post(v_app_url || '/payment-hooks/init-reconciler',
                   jsonb_build_object('orders', v_orders)::text, 'application/json');

  IF v_resp.status IS NULL OR v_resp.status < 200 OR v_resp.status > 299 THEN
    RAISE NOTICE 'job_payment_init_reconciler: POST returned %, will retry next tick', v_resp.status;
    RETURN 0;
  END IF;

  INSERT INTO public.payment_event (provider_event_id, order_id, kind, payload)
  SELECT 'ordelo:init_reconcile_alerted:' || (o->>'order_id'),
         o->>'order_id', 'init_reconcile_alerted', o
    FROM jsonb_array_elements(v_orders) AS o
  ON CONFLICT (provider_event_id) DO NOTHING;

  RETURN v_count;
END $$;


-- ---------------------------------------------------------------------------
-- 003  R1b: notification subscriptions, customer events, outbox (unused until R1b)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.order_notification_subscription (
  id             BIGSERIAL PRIMARY KEY,
  order_number   TEXT NOT NULL REFERENCES public.food_order(order_number) ON DELETE CASCADE,
  channel        TEXT NOT NULL CHECK (channel IN ('whatsapp_restaurant','whatsapp_agg','web_page')),
  destination    TEXT NULL,       -- recipient phone for whatsapp_*; NULL for web_page
  detail_level   TEXT NOT NULL DEFAULT 'full' CHECK (detail_level IN ('full','status_only')),
  active         BOOLEAN NOT NULL DEFAULT TRUE,
  source         TEXT NOT NULL,   -- 'order_origin' | 'wa_handoff'
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  deactivated_at TIMESTAMPTZ NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ons_unique_active
  ON public.order_notification_subscription (order_number, channel, COALESCE(destination, ''))
  WHERE active;

CREATE TABLE IF NOT EXISTS public.order_customer_event (
  id            BIGSERIAL PRIMARY KEY,
  order_number  TEXT NOT NULL REFERENCES public.food_order(order_number) ON DELETE CASCADE,
  event_key     TEXT NOT NULL,   -- deterministic, e.g. 'payment_authorised', 'rider_assigned:<dispatch_id>'
  event_type    TEXT NOT NULL,   -- plan §7.4
  occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  is_estimate   BOOLEAN NOT NULL DEFAULT FALSE,
  data          JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT order_customer_event_key_uq UNIQUE (order_number, event_key)
);

CREATE TABLE IF NOT EXISTS public.notification_outbox (
  id              BIGSERIAL PRIMARY KEY,
  event_id        BIGINT NOT NULL REFERENCES public.order_customer_event(id) ON DELETE CASCADE,
  subscription_id BIGINT NOT NULL REFERENCES public.order_notification_subscription(id) ON DELETE CASCADE,
  status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed','skipped')),
  attempts        INTEGER NOT NULL DEFAULT 0,
  last_error      TEXT NULL,
  next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT notification_outbox_uq UNIQUE (event_id, subscription_id)
);
CREATE INDEX IF NOT EXISTS notification_outbox_due
  ON public.notification_outbox (status, next_attempt_at);

COMMIT;


-- ===========================================================================
-- 4. AFTER THE FILE HAS RUN: verification, then flags (one at a time)
-- ===========================================================================
-- Verify:
--   SELECT column_name, column_default FROM information_schema.columns
--    WHERE table_name = 'food_order' AND column_name IN ('origin_channel','storefront','idempotency_key');
--   SELECT count(*) FROM food_order WHERE origin_channel <> 'whatsapp' OR storefront <> 'direct';  -- expect 0
--   SELECT record_payment_authorised('test:does-not-exist', 'NO-SUCH-ORDER');                     -- {"outcome":"unknown_order"}
--
-- Flags read by the app (60 s cache; a missing key means off). Enable on the
-- test restaurant first, one at a time:
--   INSERT INTO ordelo_config (config_key, config_value, description) VALUES
--     ('PAYMENT_INBOX_ENABLED',      'true', 'ordelo-agg R1a: payment-complete via record_payment_authorised'),
--     ('ORDER_CREATE_RPC_ENABLED',   'true', 'ordelo-agg R1a: create order + items in one transaction'),
--     ('ENABLE_PAYMENT_TEST_ROUTES', 'false','ordelo-agg R1a: /payment-hooks/payment-complete-test (keep false in prod)')
--   ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = now();
--
-- Init reconciler (alert-only): set the start time, then schedule.
--   INSERT INTO ordelo_config (config_key, config_value, description)
--   VALUES ('PAYMENT_INIT_RECONCILER_SINCE', now()::text, 'ordelo-agg R1a: reconcile orders created after this')
--   ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = now();
--   SELECT cron.schedule('job_payment_init_reconciler', '*/2 * * * *', $$SELECT job_payment_init_reconciler()$$);
--
-- Roll back a flag:      UPDATE ordelo_config SET config_value = 'false' WHERE config_key = '<KEY>';
-- Stop the reconciler:   SELECT cron.unschedule('job_payment_init_reconciler');
