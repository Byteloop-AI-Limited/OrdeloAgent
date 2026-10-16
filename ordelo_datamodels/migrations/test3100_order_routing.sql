-- MIGRATION (history; do not edit the statements below)
-- Applied to live: Applied: every object it creates exists live (checked 2026-10-16).
-- Current definitions now live in: dispatch/job_create_dispatch.sql
--               ordering/create_food_order_with_items.sql
--               ordering/order_has_test_item.sql
-- Purpose: TEST3100 order routing (order_has_test_item, dispatch restriction) and removal of an earlier version.
-- The feature files above are the current truth; this file only records the one-off change.

-- TEST3100 routing for new orders only. No historical order scan or backfill.
-- If the earlier version was already run, only the three DROP statements below
-- are needed to remove its extra artifacts. They do not change any order rows.

DROP TRIGGER IF EXISTS food_order_payment_environment_fixed ON public.food_order;
DROP FUNCTION IF EXISTS public.forbid_payment_environment_change();
DROP FUNCTION IF EXISTS public.assert_test_order_cutover_ready();

-- Required routing functions. CREATE OR REPLACE keeps this file repeatable.
-- Exact, order-scoped marker lookup. NULL means the order does not exist.
CREATE OR REPLACE FUNCTION public.order_has_test_item(p_order_number text)
RETURNS boolean LANGUAGE sql STABLE SET search_path = public AS $$
  SELECT EXISTS (
    SELECT 1 FROM order_item oi
    WHERE oi.order_id = fo.order_id AND oi.product_name = 'TEST3100'
  )
  FROM food_order fo WHERE fo.order_number = p_order_number;
$$;

-- ---------------------------------------------------------------------------
-- R1a  F4: create the order and its items in one transaction
-- ---------------------------------------------------------------------------
-- p_order: {order_id, order_number, seq_id, recipient, notes, thread_id, action,
--           total_price, payment_status?, origin_channel?, storefront?}
-- p_items: [{product_name, sku, quantity, price, modifications?}, …]
-- Payment environment is derived from these items, never caller-selected.
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

CREATE OR REPLACE FUNCTION get_available_riders(p_order_number text, p_town text, p_vehicle_type text)
RETURNS TABLE(rider_id VARCHAR(12), priority INT) AS $$
BEGIN
    RETURN QUERY
    WITH ridersToExclude AS (
        SELECT DISTINCT dDispatch.rider_id, dDispatch.vehicle_type
        FROM delivery_dispatch dDispatch
        WHERE dDispatch.order_number = p_order_number 
        UNION 
        SELECT DISTINCT inflight.rider_id, 'inflight'
        FROM delivery_inflight inflight
    )
    SELECT 
        allRiders.rider_id,
        allRiders.priority
    FROM rider_master allRiders 
    WHERE 
    LOWER(allRiders.town)=LOWER(p_town)
    AND allRiders.vehicle_type = p_vehicle_type
    AND allRiders.is_in_shift
    -- Restrict before priority/batch ranking. Unknown orders have no candidates.
    AND CASE public.order_has_test_item(p_order_number)
      WHEN false THEN true
      WHEN true THEN EXISTS (
        SELECT 1 FROM ordelo_config oc,
          LATERAL regexp_split_to_table(COALESCE(oc.config_value, ''), ',') AS member(number)
        WHERE oc.config_key = 'overwatch_list'
          AND btrim(member.number) = allRiders.rider_id
      )
      ELSE false
    END
    AND NOT EXISTS 
    (SELECT 1 FROM ridersToExclude WHERE ridersToExclude.rider_id = allRiders.rider_id);

END;
$$ LANGUAGE plpgsql;


-- Remove only the obsolete restaurant-wide payment setting; never order data.
DELETE FROM public.ordelo_config
WHERE config_key = 'TEST_PAYMENT_' || 'REST_REFS'
RETURNING config_key;

-- Definition verification only; no historical order inspection.
SELECT to_regprocedure('public.create_food_order_with_items(jsonb,jsonb)') AS order_creation,
       to_regprocedure('public.order_has_test_item(text)') AS marker_lookup,
       to_regprocedure('public.get_available_riders(text,text,text)') AS rider_candidates;
