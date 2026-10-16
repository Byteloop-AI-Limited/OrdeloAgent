ALTER TABLE public.food_order
    ADD COLUMN IF NOT EXISTS origin_channel text NOT NULL DEFAULT 'whatsapp'::text;

-- added by migrations/ordelo_agg_r1.sql
ALTER TABLE public.food_order
    ADD COLUMN IF NOT EXISTS storefront text NOT NULL DEFAULT 'direct'::text;

-- added by migrations/ordelo_agg_r1.sql
ALTER TABLE public.food_order
    ADD COLUMN IF NOT EXISTS idempotency_key text;

-- used by web create-order (R3) -- added by migrations/ordelo_agg_r1.sql
ALTER TABLE public.food_order
    ADD COLUMN IF NOT EXISTS payment_mode text;

-- added by migrations/ordelo_agg_r1.sql
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

-- order_item is keyed by order_id (FK to food_order.order_id).
-- The items endpoint looks up items by order_id from a parent food_order row.
CREATE INDEX IF NOT EXISTS idx_order_item_order_id ON public.order_item USING btree (order_id);

-- Definition taken from the live database on 2026-10-16 (no repo copy existed).
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

DROP TRIGGER IF EXISTS food_order_origin_immutable ON public.food_order;

CREATE TRIGGER food_order_origin_immutable
    BEFORE UPDATE OF origin_channel,
    storefront ON food_order
    FOR EACH ROW
    EXECUTE FUNCTION forbid_food_order_origin_change ();
