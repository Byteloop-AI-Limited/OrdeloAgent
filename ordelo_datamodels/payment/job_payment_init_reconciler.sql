-- =============================================================================================
-- ordelo_datamodels/payment/job_payment_init_reconciler.sql
-- Alert overwatch about paid orders that never started fulfilment (alert-only, once per order).
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16): every object below was compared with the live catalogue.
-- OBJECTS       fn     job_payment_init_reconciler() -> integer
--                   Find paid orders with no fulfilment row, POST them to the init-reconciler hook, and mark each as alerted; returns how many.
-- REQUIRES      none
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  HTTP POST to /payment-hooks/init-reconciler; inserts payment_event rows on success.
-- HOW IT FITS   Meant to run from pg_cron every 2 minutes (NOT scheduled on live: docs/to-do.md).
--                 Finds food_order rows with payment_status 'requires_capture', created after ordelo_config
--                 PAYMENT_INIT_RECONCILER_SINCE, authorised more than 2 minutes ago, with no delivery_summary / takeaway_summary row
--                 and no earlier alert -> POST {ORDELO_APP_URL}/payment-hooks/init-reconciler {orders:[...]} -> overwatch alert.
--                 On a 2xx answer each order gets a payment_event 'init_reconcile_alerted' so it is alerted once.
-- LIFECYCLE     Disabled while PAYMENT_INIT_RECONCILER_SINCE is empty (returns 0).
-- CALLED BY     job_payment_init_reconciler:
--                 python    watomation/routers/payment_hooks.py (module-level SQL)
-- PYTHON MODEL  none
-- SECURITY      job_payment_init_reconciler(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       Not scheduled in cron.job on 2026-10-16 although migrations/ordelo_agg_r1.sql says to schedule it (docs/to-do.md).
--               Falls back to https://agent.ordelo.app when ORDELO_APP_URL is empty.
-- SEE ALSO      payment/payment_event.sql
--               watomation/routers/payment_hooks.py (init_reconciler_path)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function job_payment_init_reconciler() -> integer
--   Find paid orders with no fulfilment row, POST them to the init-reconciler hook, and mark each as alerted; returns how many.
--   Data: reads delivery_summary, food_order, ordelo_config, takeaway_summary; writes payment_event.
--   HTTP: POST /payment-hooks/init-reconciler -> watomation/routers/payment_hooks.py::init_reconciler_path
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.job_payment_init_reconciler ()
    RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_since timestamptz;
    v_app_url text;
    v_orders jsonb;
    v_count integer;
    v_resp http_response;
BEGIN
    SELECT
        NULLIF (config_value, '')::timestamptz INTO v_since
    FROM
        public.ordelo_config
    WHERE
        config_key = 'PAYMENT_INIT_RECONCILER_SINCE';
    IF v_since IS NULL THEN
        RETURN 0;
    END IF;

    WITH stuck AS (
        SELECT
            fo.order_id,
            fo.order_number,
            fo.action,
            COALESCE((
                SELECT
                    max(pe.received_at)
                FROM public.payment_event pe
                WHERE
                    pe.order_id = fo.order_id
                    AND pe.kind = 'authorised'), fo.order_dtts) AS authorised_at
    FROM
        public.food_order fo
    WHERE
        fo.payment_status = 'requires_capture'
        AND fo.order_dtts >= v_since
        AND NOT EXISTS (
            SELECT
                1
            FROM
                public.payment_event pe
            WHERE
                pe.order_id = fo.order_id
                AND pe.kind = 'init_reconcile_alerted')
            AND NOT (fo.action = 'delivery'
                AND EXISTS (
                    SELECT
                        1
                    FROM
                        public.delivery_summary ds
                    WHERE
                        ds.order_number = fo.order_number))
                AND NOT (fo.action = 'takeaway'
                    AND EXISTS (
                        SELECT
                            1
                        FROM
                            public.takeaway_summary ts
                        WHERE
                            ts.order_number = fo.order_number)))
        SELECT
            jsonb_agg(jsonb_build_object('order_id', order_id, 'order_number', order_number, 'action', action, 'authorised_at', authorised_at)),
        count(*) INTO v_orders,
    v_count
FROM
    stuck
WHERE
    authorised_at < now() - interval '2 minutes';

    IF COALESCE(v_count, 0) = 0 THEN
        RETURN 0;
    END IF;

    SELECT
        config_value INTO v_app_url
    FROM
        public.ordelo_config
    WHERE
        config_key = 'ORDELO_APP_URL';
    IF v_app_url IS NULL OR length(v_app_url) = 0 THEN
        v_app_url := 'https://agent.ordelo.app';
    END IF;
    IF
    RIGHT (v_app_url,
    1) = '/' THEN
        v_app_url :=
    LEFT (v_app_url,
        length(v_app_url) - 1);
    END IF;

    SELECT
        * INTO v_resp
    FROM
        http_post (v_app_url || '/payment-hooks/init-reconciler', jsonb_build_object('orders', v_orders)::text, 'application/json');

    IF v_resp.status IS NULL OR v_resp.status < 200 OR v_resp.status > 299 THEN
        RAISE NOTICE 'job_payment_init_reconciler: POST returned %, will retry next tick', v_resp.status;
        RETURN 0;
    END IF;

    INSERT INTO public.payment_event (provider_event_id, order_id, kind, payload)
    SELECT
        'ordelo:init_reconcile_alerted:' || (o ->> 'order_id'),
        o ->> 'order_id',
        'init_reconcile_alerted',
        o
    FROM
        jsonb_array_elements(v_orders) AS o
ON CONFLICT (provider_event_id)
    DO NOTHING;

    RETURN v_count;
END
$$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.job_payment_init_reconciler () IS 'Find paid orders with no fulfilment row, POST them to the init-reconciler hook, and mark each as alerted; returns how many.';
