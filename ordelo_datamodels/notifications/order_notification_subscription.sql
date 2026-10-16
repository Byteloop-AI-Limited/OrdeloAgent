-- =============================================================================================
-- ordelo_datamodels/notifications/order_notification_subscription.sql
-- Who is subscribed to an order's progress updates, on which channel and at which detail level.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  order_notification_subscription
--                   Subscription of a destination to an order's events. channel: whatsapp_restaurant | whatsapp_agg | web_page; detail_level: full | status_only.
-- REQUIRES      restaurant-agents: food_order
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   Customer progress notifications (R1b; utils_common/notify/customer_notifier.py, docs/alerts-and-notifications.md):
--                 order_notification_subscription  who should hear about an order (channel, destination, detail level)
--                 order_customer_event             what happened (one row per order x event_key, deterministic keys)
--                 notification_outbox              one delivery attempt record per event x subscription (claim before I/O)
--                 Web orders get a 'web_page' subscription with no destination (the page reads events directly);
--                 WhatsApp customers get 'whatsapp_restaurant'. All three cascade-delete with the food_order.
-- LIFECYCLE     active = false (with deactivated_at) instead of deleting; one active row per order/channel/destination.
-- CALLED BY     order_notification_subscription:
--                 python    utils_common/notify/customer_notifier.py: _claim(), _ensure_origin_subscription(), _record(), sweep_pending()
-- PYTHON MODEL  none
-- SECURITY      order_notification_subscription: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         tests/sql/test_restaurant_notices_script_sql.py
--               tests/utils_common/test_customer_notifier.py
-- GOTCHAS       none
-- SEE ALSO      notifications/order_customer_event.sql
--               notifications/notification_outbox.sql
--               docs/alerts-and-notifications.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table order_notification_subscription
--   Subscription of a destination to an order's events. channel: whatsapp_restaurant | whatsapp_agg | web_page; detail_level: full | status_only.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.order_notification_subscription (
    id bigserial NOT NULL,
    order_number text NOT NULL,
    channel text NOT NULL,
    destination text, -- recipient phone for whatsapp_*; NULL for web_page
    detail_level text NOT NULL DEFAULT 'full' ::text,
    active boolean NOT NULL DEFAULT TRUE,
    source text NOT NULL, -- 'order_origin' | 'wa_handoff'
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    deactivated_at timestamp with time zone,
    CONSTRAINT order_notification_subscription_pkey PRIMARY KEY (id),
    CONSTRAINT order_notification_subscription_channel_check CHECK ((channel = ANY (ARRAY['whatsapp_restaurant'::text, 'whatsapp_agg'::text, 'web_page'::text]))),
    CONSTRAINT order_notification_subscription_detail_level_check CHECK ((detail_level = ANY (ARRAY['full'::text, 'status_only'::text]))),
    CONSTRAINT order_notification_subscription_order_number_fkey FOREIGN KEY (order_number) REFERENCES food_order (order_number) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ons_unique_active ON public.order_notification_subscription USING btree (order_number, channel, COALESCE(destination, ''::text))
WHERE
    active;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.order_notification_subscription IS 'Subscription of a destination to an order''s events. channel: whatsapp_restaurant | whatsapp_agg | web_page; detail_level: full | status_only.';
