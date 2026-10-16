-- ---------------------------------------------------------------------------
-- 003  R1b: notification subscriptions, customer events, outbox (unused until R1b)
-- ---------------------------------------------------------------------------
-- (The statement that followed this comment is now generated from live in notifications/order_notification_subscription.sql.)
CREATE TABLE IF NOT EXISTS public.notification_outbox (
    id bigserial NOT NULL,
    event_id bigint NOT NULL,
    subscription_id bigint NOT NULL,
    status text NOT NULL DEFAULT 'pending' ::text,
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    next_attempt_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT notification_outbox_pkey PRIMARY KEY (id),
    CONSTRAINT notification_outbox_uq UNIQUE (event_id, subscription_id),
    CONSTRAINT notification_outbox_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'sent'::text, 'failed'::text, 'skipped'::text]))),
    CONSTRAINT notification_outbox_event_id_fkey FOREIGN KEY (event_id) REFERENCES order_customer_event (id) ON DELETE CASCADE,
    CONSTRAINT notification_outbox_subscription_id_fkey FOREIGN KEY (subscription_id) REFERENCES order_notification_subscription (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS notification_outbox_due ON public.notification_outbox USING btree (status, next_attempt_at);
