-- =============================================================================================
-- ordelo_datamodels/notifications/notification_outbox.sql
-- Delivery bookkeeping for customer notifications: one row per event and subscription.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  notification_outbox
--                   One row per (event, subscription): status pending | sent | failed | skipped, with attempts and last error.
-- REQUIRES      notifications/order_customer_event.sql
--               notifications/order_notification_subscription.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   Customer progress notifications (R1b; utils_common/notify/customer_notifier.py, docs/alerts-and-notifications.md):
--                 order_notification_subscription  who should hear about an order (channel, destination, detail level)
--                 order_customer_event             what happened (one row per order x event_key, deterministic keys)
--                 notification_outbox              one delivery attempt record per event x subscription (claim before I/O)
--                 Web orders get a 'web_page' subscription with no destination (the page reads events directly);
--                 WhatsApp customers get 'whatsapp_restaurant'. All three cascade-delete with the food_order.
-- LIFECYCLE     status: pending -> sent | failed | skipped; attempts and next_attempt_at drive retries.
-- CALLED BY     notification_outbox:
--                 python    utils_common/notify/customer_notifier.py: _claim(), _finish(), _record(), sweep_pending()
-- PYTHON MODEL  none
-- SECURITY      notification_outbox: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         tests/sql/test_restaurant_notices_script_sql.py
--               tests/utils_common/test_customer_notifier.py
-- GOTCHAS       Restaurant-app (WhatsApp) delivery is attempted once; web_page delivery is a no-op (the page reads events).
-- SEE ALSO      notifications/order_customer_event.sql
--               notifications/order_notification_subscription.sql
--               docs/alerts-and-notifications.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table notification_outbox
--   One row per (event, subscription): status pending | sent | failed | skipped, with attempts and last error.
-- ---------------------------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.notification_outbox IS 'One row per (event, subscription): status pending | sent | failed | skipped, with attempts and last error.';
