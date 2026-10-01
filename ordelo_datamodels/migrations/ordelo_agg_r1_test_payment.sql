-- ===========================================================================
-- ordelo-agg R1a addendum: test payments on request (plan D32)
-- ===========================================================================
-- Run manually, once, after ordelo_agg_r1.sql. Idempotent and additive.
--
-- food_order.payment_mode records which payment service an order uses, chosen
-- once at create-order: 'test' when Ordelo honoured a ?isTest3100=true request,
-- 'live' or NULL otherwise (NULL = today's rule: overwatch + delivery -> test).
-- Capture and cancel read the same value, so they reach the same service.
-- ===========================================================================

BEGIN;

ALTER TABLE public.food_order
  ADD COLUMN IF NOT EXISTS payment_mode TEXT NULL
      CONSTRAINT food_order_payment_mode_chk CHECK (payment_mode IN ('live','test'));

-- Same function as in ordelo_agg_r1.sql, now also writing payment_mode.
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
    total_price, payment_status, origin_channel, storefront, payment_mode)
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
    NULLIF(p_order->>'payment_mode', ''))
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

COMMIT;

-- Then list the restaurants whose web orders may use test payments (comma-separated):
--   INSERT INTO ordelo_config (config_key, config_value, description)
--   VALUES ('TEST_PAYMENT_REST_REFS', 'BNAT', 'ordelo-agg D32: restaurants that honour ?isTest3100=true')
--   ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value, updated_at = now();
-- Verify:
--   SELECT column_name FROM information_schema.columns WHERE table_name = 'food_order' AND column_name = 'payment_mode';
