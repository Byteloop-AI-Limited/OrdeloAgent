-- =============================================================================================
-- ordelo_datamodels/ordering/food_order_additions.sql
-- Columns, constraints, an index and a guard trigger that OrdeloAgent adds to restaurant-agents' food_order / order_item.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       alter  food_order (table owned by restaurant-agents)
--                   columns     origin_channel, storefront, idempotency_key, payment_mode
--                   constraints food_order_origin_channel_chk, food_order_storefront_chk, food_order_payment_mode_chk
--                   indexes     food_order_idempotency_key_uq
--               alter  order_item (table owned by restaurant-agents)
--                   indexes     idx_order_item_order_id
--               fn     forbid_food_order_origin_change() -> trigger
--                   Trigger function: RAISE if an UPDATE changes food_order.origin_channel or storefront.
--               trg    food_order_origin_immutable on food_order -> forbid_food_order_origin_change()
--                   BEFORE UPDATE OF origin_channel, storefront on food_order: runs forbid_food_order_origin_change().
-- REQUIRES      restaurant-agents: food_order
--               restaurant-agents: order_item
-- HOW TO RUN    Supabase SQL editor, whole file, AFTER restaurant-agents has created food_order and order_item.
--               Safe to re-run: ADD COLUMN IF NOT EXISTS, DROP/ADD CONSTRAINT, CREATE INDEX IF NOT EXISTS, CREATE OR REPLACE.
-- SIDE EFFECTS  Applying the file ALTERs food_order (adds columns only if missing, re-creates three CHECK constraints) and
--               re-creates the trigger. Re-creating a CHECK constraint re-validates existing rows (brief lock).
-- HOW IT FITS   food_order and order_item are created by restaurant-agents (services/order_management/food_order.sql there).
--                 OrdeloAgent's web ordering needs extra columns, so they are added here with idempotent ALTERs instead of copying
--                 the restaurant-agents DDL:
--                   origin_channel  'whatsapp' | 'web'      where the order began; immutable (trigger below)
--                   storefront      'direct' | 'ordelo'     which storefront sold it; immutable
--                   payment_mode    'live' | 'test'         Stripe environment, set by create_food_order_with_items()
--                   idempotency_key                          web create-order retries return the same order (unique when set)
--                 idx_order_item_order_id serves the admin dashboard views (admin_dashboard/v_admin_orders.sql).
-- LIFECYCLE     none
-- CALLED BY     forbid_food_order_origin_change:
--                 trigger   food_order_origin_immutable on food_order
-- PYTHON MODEL  none
-- SECURITY      forbid_food_order_origin_change(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       If restaurant-agents ever adds a column with the same name, its definition must match this one.
--               Defined first in migrations/ordelo_agg_r1.sql and ordelo_agg_r1_test_payment.sql (history).
-- SEE ALSO      ordering/create_food_order_with_items.sql
--               docs/web-ordering-playground.md (origin / storefront / fulfilment)
-- =============================================================================================
ALTER TABLE public.food_order
    ADD COLUMN IF NOT EXISTS origin_channel text NOT NULL DEFAULT 'whatsapp'::text;

ALTER TABLE public.food_order
    ADD COLUMN IF NOT EXISTS storefront text NOT NULL DEFAULT 'direct'::text;

ALTER TABLE public.food_order
    ADD COLUMN IF NOT EXISTS idempotency_key text;

ALTER TABLE public.food_order
    ADD COLUMN IF NOT EXISTS payment_mode text;

ALTER TABLE public.food_order
    DROP CONSTRAINT IF EXISTS food_order_origin_channel_chk;

ALTER TABLE public.food_order
    ADD CONSTRAINT food_order_origin_channel_chk CHECK ((origin_channel = ANY (ARRAY['whatsapp'::text, 'web'::text])));

ALTER TABLE public.food_order
    DROP CONSTRAINT IF EXISTS food_order_storefront_chk;

ALTER TABLE public.food_order
    ADD CONSTRAINT food_order_storefront_chk CHECK ((storefront = ANY (ARRAY['direct'::text, 'ordelo'::text])));

ALTER TABLE public.food_order
    DROP CONSTRAINT IF EXISTS food_order_payment_mode_chk;

ALTER TABLE public.food_order
    ADD CONSTRAINT food_order_payment_mode_chk CHECK ((payment_mode = ANY (ARRAY['live'::text, 'test'::text])));

CREATE UNIQUE INDEX IF NOT EXISTS food_order_idempotency_key_uq ON public.food_order USING btree (idempotency_key)
WHERE (idempotency_key IS NOT NULL);

CREATE INDEX IF NOT EXISTS idx_order_item_order_id ON public.order_item USING btree (order_id);

-- ---------------------------------------------------------------------------------------------
-- function forbid_food_order_origin_change() -> trigger
--   Trigger function: RAISE if an UPDATE changes food_order.origin_channel or storefront.
--   Both describe how the order began and are fixed once written.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.forbid_food_order_origin_change ()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $function$
BEGIN
    IF NEW.origin_channel IS DISTINCT FROM OLD.origin_channel THEN
        RAISE EXCEPTION 'food_order.origin_channel is immutable (order %)', OLD.order_number;
    END IF;
    IF NEW.storefront IS DISTINCT FROM OLD.storefront THEN
        RAISE EXCEPTION 'food_order.storefront is immutable (order %)', OLD.order_number;
    END IF;
    RETURN NEW;
END
$function$;

-- ---------------------------------------------------------------------------------------------
-- trigger food_order_origin_immutable on food_order -> forbid_food_order_origin_change()
--   BEFORE UPDATE OF origin_channel, storefront on food_order: runs forbid_food_order_origin_change().
-- ---------------------------------------------------------------------------------------------
DROP TRIGGER IF EXISTS food_order_origin_immutable ON public.food_order;

CREATE TRIGGER food_order_origin_immutable
    BEFORE UPDATE OF origin_channel,
    storefront ON food_order
    FOR EACH ROW
    EXECUTE FUNCTION forbid_food_order_origin_change ();

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.forbid_food_order_origin_change () IS 'Trigger function: RAISE if an UPDATE changes food_order.origin_channel or storefront.';

COMMENT ON TRIGGER food_order_origin_immutable ON public.food_order IS 'BEFORE UPDATE OF origin_channel, storefront on food_order: runs forbid_food_order_origin_change().';
