-- =============================================================================================
-- ordelo_datamodels/notifications/order_customer_event.sql
-- Customer-visible order progress events, one row per order and deterministic event key.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       table  order_customer_event
--                   One progress fact per order and event_key (e.g. 'payment_authorised', 'rider_assigned:<dispatch_id>'), with a safe data payload.
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
-- LIFECYCLE     append-only; the unique (order_number, event_key) makes writers idempotent.
-- CALLED BY     order_customer_event:
--                 python    utils_common/notify/customer_notifier.py: _claim(), _record(), publish(), sweep_pending()
--                 python    utils_common/web_ordering/customer_order_view.py: get_view()
--                 python    utils_common/web_ordering/lifecycle.py: release()
-- PYTHON MODEL  none
-- SECURITY      order_customer_event: RLS OFF; Supabase default grants (anon and authenticated can read and write)
-- TESTS         tests/sql/test_restaurant_notices_script_sql.py
--               tests/utils_common/test_customer_notifier.py
-- GOTCHAS       none
-- SEE ALSO      notifications/order_notification_subscription.sql
--               notifications/notification_outbox.sql
--               docs/alerts-and-notifications.md
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- table order_customer_event
--   One progress fact per order and event_key (e.g. 'payment_authorised', 'rider_assigned:<dispatch_id>'), with a safe data payload.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.order_customer_event (
    id bigserial NOT NULL,
    order_number text NOT NULL,
    event_key text NOT NULL, -- deterministic, e.g. 'payment_authorised', 'rider_assigned:<dispatch_id>'
    event_type text NOT NULL, -- plan §7.4
    occurred_at timestamp with time zone NOT NULL DEFAULT now(),
    is_estimate boolean NOT NULL DEFAULT FALSE,
    data jsonb NOT NULL DEFAULT '{}' ::jsonb,
    CONSTRAINT order_customer_event_pkey PRIMARY KEY (id),
    CONSTRAINT order_customer_event_key_uq UNIQUE (order_number, event_key),
    CONSTRAINT order_customer_event_order_number_fkey FOREIGN KEY (order_number) REFERENCES food_order (order_number) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON TABLE public.order_customer_event IS 'One progress fact per order and event_key (e.g. ''payment_authorised'', ''rider_assigned:<dispatch_id>''), with a safe data payload.';
