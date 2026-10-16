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
