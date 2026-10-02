-- R3 additive web checkout/access storage. Does not enable any restaurant.
-- Existing WhatsApp order creation retains the same parameters/defaults.
BEGIN;
ALTER TABLE restaurant_master ADD COLUMN IF NOT EXISTS delivery_order_cutoff_minutes integer NOT NULL DEFAULT 0,
 ADD COLUMN IF NOT EXISTS takeaway_order_cutoff_minutes integer NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS public.order_access_grant (
 id bigserial PRIMARY KEY, order_number text NOT NULL REFERENCES food_order(order_number),
 kind text NOT NULL CHECK(kind IN ('page_token','wa_handoff')), secret_hash bytea NOT NULL UNIQUE,
 detail_level text NOT NULL DEFAULT 'full', expires_at timestamptz NOT NULL,
 consumed_at timestamptz, consumed_by text, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS public.web_session_meta (
 thread_id text PRIMARY KEY REFERENCES thread(thread_id), visitor_id text NOT NULL,
 cust_id text NOT NULL UNIQUE, rest_ref varchar(4) NOT NULL, mode text NOT NULL CHECK(mode IN ('delivery','collection')),
 town_slug text NOT NULL, postcode_district text, device_class text, utm jsonb NOT NULL DEFAULT '{}',
 referrer_host text, address jsonb, expires_at timestamptz NOT NULL DEFAULT now()+interval '2 hours',
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS public.web_order_request (
 idempotency_key text PRIMARY KEY, thread_id text NOT NULL REFERENCES thread(thread_id),
 body_hash text NOT NULL, order_number text NOT NULL UNIQUE REFERENCES food_order(order_number),
 address jsonb, quote jsonb, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS public.web_rate_limit (
 identity_hash text NOT NULL, window_start timestamptz NOT NULL, attempts integer NOT NULL DEFAULT 1,
 PRIMARY KEY(identity_hash,window_start));
CREATE TABLE IF NOT EXISTS public.web_payment_release (
 order_number text PRIMARY KEY REFERENCES food_order(order_number), reason text NOT NULL,
 attempts integer NOT NULL DEFAULT 0, completed_at timestamptz, next_attempt_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS public.web_monitor_run (
 run_day date PRIMARY KEY, completed_at timestamptz, alert_orders text[] NOT NULL DEFAULT '{}');
ALTER TABLE web_monitor_run ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON web_monitor_run FROM anon,authenticated;
ALTER TABLE order_access_grant ENABLE ROW LEVEL SECURITY;
ALTER TABLE web_session_meta ENABLE ROW LEVEL SECURITY;
ALTER TABLE web_order_request ENABLE ROW LEVEL SECURITY;
ALTER TABLE web_rate_limit ENABLE ROW LEVEL SECURITY;
ALTER TABLE web_payment_release ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON order_access_grant,web_session_meta,web_order_request,web_rate_limit,web_payment_release FROM anon,authenticated;

-- Preserve current admin view definition/filters and append origin_channel.
DO $$ DECLARE definition text; BEGIN
 IF to_regclass('public.v_admin_orders') IS NOT NULL AND NOT EXISTS (
 SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='v_admin_orders' AND column_name='origin_channel') THEN
  definition := rtrim(pg_get_viewdef('public.v_admin_orders'::regclass,true), '; ');
  EXECUTE 'CREATE OR REPLACE VIEW public.v_admin_orders AS SELECT existing.*,fo.origin_channel FROM ('||definition||') existing JOIN public.food_order fo ON fo.order_number=existing.order_number';
 END IF;
END $$;
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
    NULLIF(p_order->>'payment_mode', ''), NULLIF(p_order->>'idempotency_key', ''))
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

CREATE OR REPLACE FUNCTION job_close_thread()
RETURNS BOOLEAN AS $$
DECLARE
    interval_minutes INT;
    interval_expr INTERVAL;
    webhook_payload JSON;
    response JSON;
    notified BOOLEAN := FALSE;
    ordelo_app_url TEXT;
    webhook_url TEXT;
BEGIN
    -- Get the interval in minutes from config
    SELECT config_value::int INTO interval_minutes FROM ordelo_config WHERE config_key = 'THREAD_INACTIVE_TIME_INTERVAL';
    IF interval_minutes IS NULL THEN
        interval_minutes := 5; -- Default fallback (5 minutes)
    END IF;
    interval_expr := (interval_minutes || ' minutes')::interval;

    -- Get the base app URL from config
    SELECT config_value INTO ordelo_app_url FROM ordelo_config WHERE config_key = 'ORDELO_APP_URL';
    IF ordelo_app_url IS NULL OR ordelo_app_url = '' THEN
        ordelo_app_url := 'https://rider-agent.ordelo.app'; -- Fallback default
    END IF;
    webhook_url := ordelo_app_url || '/delivery-hooks/close-threads';

    WITH threads_to_close AS (
        SELECT
            thread_id,
            recipient,
            last_access_dtts,
            is_active,
            EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - last_access_dtts))/60 AS minutes_since_last_access
        FROM thread
        WHERE last_access_dtts IS NOT NULL
          AND CURRENT_TIMESTAMP - last_access_dtts > interval_expr
          AND retain_thread = FALSE
          AND is_active = TRUE
          AND recipient IS NOT NULL
          AND agent IS DISTINCT FROM 'WEB'
    )
    SELECT json_agg(
        json_build_object(
            'thread_id', thread_id, 
            'recipient', recipient, 
            'last_access_dtts', last_access_dtts,
            'is_active', is_active,
            'minutes_since_last_access', minutes_since_last_access
        )
    )
    INTO webhook_payload
    FROM threads_to_close;

    -- Only POST if there is at least one thread to close
    IF webhook_payload IS NOT NULL THEN
        response := (
            SELECT content
            FROM http_post(
                webhook_url,
                webhook_payload::text,
                'application/json'
            )
        );
        RAISE NOTICE 'Response from close-threads: %', response;
        notified := TRUE;
    ELSE
        RAISE NOTICE 'No threads to close.';
        notified := FALSE;
    END IF;
    RETURN notified;
END;
$$ LANGUAGE plpgsql;
COMMIT;
-- Explicit opt-in after code/secrets/checks: WEB_ORDERING_ENABLED_REST_REFS=ELAS
-- WEB_LATE_PAYMENT_GUARD_ENABLED=true; existing TEST_PAYMENT_REST_REFS is reused (D32).
