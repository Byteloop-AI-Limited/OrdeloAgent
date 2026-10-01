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

