CREATE OR REPLACE VIEW public.v_admin_orders AS
 SELECT existing.order_number,
    existing.rest_ref,
    existing.type,
    existing.status,
    existing.rest_confirmation_code,
    existing.pickup_time,
    existing.created_at,
    existing.customer_name,
    existing.pickup_day_local,
    existing.created_day_local,
    existing.sort_time,
    existing.sort_day_local,
    existing.total_price,
    existing.rest_cost,
    existing.commission_rate,
    fo.origin_channel
   FROM ( SELECT ds.order_number,
            ds.rest_ref,
            'delivery'::text AS type,
            ds.status,
            ds.rest_confirmation_code,
            ds.pickup_time,
            ds.dtts AS created_at,
            ds.customer_name,
            (ds.pickup_time AT TIME ZONE 'Europe/London'::text)::date AS pickup_day_local,
            (ds.dtts AT TIME ZONE 'Europe/London'::text)::date AS created_day_local,
            COALESCE(ds.pickup_time, ds.dtts) AS sort_time,
            (COALESCE(ds.pickup_time, ds.dtts) AT TIME ZONE 'Europe/London'::text)::date AS sort_day_local,
            fo_1.total_price,
            fo_1.rest_cost,
            fo_1.commission_rate
           FROM delivery_summary ds
             JOIN food_order fo_1 ON fo_1.order_number = ds.order_number::text
          WHERE fo_1.rest_cost IS NOT NULL AND fo_1.commission_rate IS NOT NULL
        UNION ALL
         SELECT ts.order_number,
            ts.rest_ref,
            'takeaway'::text AS type,
            ts.status,
            ts.rest_confirmation_code,
            ts.pickup_time,
            ts.dtts AS created_at,
            ts.customer_name,
            (ts.pickup_time AT TIME ZONE 'Europe/London'::text)::date AS pickup_day_local,
            (ts.dtts AT TIME ZONE 'Europe/London'::text)::date AS created_day_local,
            COALESCE(ts.pickup_time, ts.dtts) AS sort_time,
            (COALESCE(ts.pickup_time, ts.dtts) AT TIME ZONE 'Europe/London'::text)::date AS sort_day_local,
            fo_1.total_price,
            fo_1.rest_cost,
            fo_1.commission_rate
           FROM takeaway_summary ts
             JOIN food_order fo_1 ON fo_1.order_number = ts.order_number::text
          WHERE ts.customer_id::text <> ALL (ARRAY['447448440754'::character varying::text, '447446933210'::character varying::text, '447919202938'::character varying::text])) existing
     JOIN food_order fo ON fo.order_number = existing.order_number::text;

CREATE OR REPLACE VIEW public.v_admin_order_items AS
 SELECT fo.order_number,
    fo.order_id,
    split_part(fo.order_number, '-'::text, 1) AS rest_ref,
    oi.product_name,
    oi.quantity,
    oi.price,
    oi.modifications
   FROM order_item oi
     JOIN food_order fo ON fo.order_id = oi.order_id;

CREATE OR REPLACE VIEW public.v_admin_orders_daily AS
 SELECT v_admin_orders.rest_ref,
    v_admin_orders.sort_day_local AS day,
    v_admin_orders.type,
    count(*) AS count,
    sum(v_admin_orders.total_price) AS gross,
    sum(v_admin_orders.rest_cost) AS your_cut
   FROM v_admin_orders
  GROUP BY v_admin_orders.rest_ref, v_admin_orders.sort_day_local, v_admin_orders.type;

CREATE OR REPLACE VIEW public.v_admin_orders_monthly AS
 SELECT v_admin_orders_daily.rest_ref,
    date_trunc('month'::text, v_admin_orders_daily.day::timestamp with time zone)::date AS month,
    v_admin_orders_daily.type,
    sum(v_admin_orders_daily.count)::bigint AS count,
    sum(v_admin_orders_daily.gross) AS gross,
    sum(v_admin_orders_daily.your_cut) AS your_cut
   FROM v_admin_orders_daily
  GROUP BY v_admin_orders_daily.rest_ref, (date_trunc('month'::text, v_admin_orders_daily.day::timestamp with time zone)::date), v_admin_orders_daily.type;
