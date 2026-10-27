-- =============================================================================================
-- ordelo_datamodels/admin_dashboard/v_admin_orders.sql
-- Order views for the restaurant admin dashboard: delivery + takeaway orders, their items, and daily / monthly totals.
-- =============================================================================================
-- LIVE CHECK    Existing definitions retained; new dashboard access restrictions/revocation are not applied (2026-10-26).
-- OBJECTS       view   v_admin_orders
--                   Delivery and takeaway orders as one list for the admin dashboard, with money and London-local day columns.
--               view   v_admin_order_items
--                   Order lines (order_item) with their order number and restaurant, for the dashboard order detail.
--               view   v_admin_orders_daily
--                   Per restaurant, local day and type: order count, gross and the restaurant's cut.
--               view   v_admin_orders_monthly
--                   v_admin_orders_daily rolled up by month.
-- REQUIRES      delivery/delivery_summary.sql
--               restaurant-agents: food_order
--               takeaway/takeaway_summary.sql
--               restaurant-agents: order_item
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none
-- HOW IT FITS   restaurant-frontend's restaurant-admin pages read these views directly (app/api/... routes, lib/rest-admin-session.ts),
--                 filtered by rest_ref:
--                   v_admin_orders           delivery_summary + takeaway_summary as one list, with food_order money columns and
--                                            London-local day columns (sort_time / sort_day_local) for paging and date filters
--                   v_admin_order_items      order_item lines joined to their order
--                   v_admin_orders_daily     per restaurant, day and type: count, gross, your_cut
--                   v_admin_orders_monthly   the daily view rolled up by month
--                 The keyset / day indexes live with the tables (delivery/delivery_summary.sql, takeaway/takeaway_summary.sql,
--                 ordering/food_order_additions.sql idx_order_item_order_id).
-- LIFECYCLE     none
-- CALLED BY     v_admin_orders:
--                 sql       v_admin_orders_daily
--                 frontend  restaurant-frontend/app/api/rest-admin/orders/route.ts
--                 frontend  restaurant-frontend/app/rest-admin/orders/_lib/server-fetcher.ts
--               v_admin_order_items:
--                 frontend  restaurant-frontend/app/api/rest-admin/orders/[order_number]/items/route.ts
--               v_admin_orders_daily:
--                 sql       v_admin_orders_monthly
--                 frontend  restaurant-frontend/app/api/rest-admin/orders/summary/route.ts
--                 frontend  restaurant-frontend/app/rest-admin/orders/_lib/server-fetcher.ts
--               v_admin_orders_monthly:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      v_admin_orders: server-only grants below (not applied)
--               v_admin_order_items: server-only grants below (not applied)
--               v_admin_orders_daily: server-only grants below (not applied)
--               v_admin_orders_monthly: server-only grants below (not applied)
-- TESTS         none
-- GOTCHAS       v_admin_orders_daily and v_admin_orders_monthly had no file in the repo before 16 Oct 2026; captured from live.
--               The views have server-only grants below (not applied): anon can read every restaurant's orders unless the frontend filters (security review).
-- SEE ALSO      migrations/admin_orders_views.sql, migrations/admin_orders_indexes.sql (history)
--               restaurant-frontend lib/rest-admin-session.ts
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- view v_admin_orders
--   Delivery and takeaway orders as one list for the admin dashboard, with money and London-local day columns.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.v_admin_orders AS
SELECT
    existing.order_number,
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
FROM (
    SELECT
        ds.order_number,
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
    FROM
        delivery_summary ds
        JOIN food_order fo_1 ON fo_1.order_number = ds.order_number::text
    WHERE
        fo_1.rest_cost IS NOT NULL
        AND fo_1.commission_rate IS NOT NULL
    UNION ALL
    SELECT
        ts.order_number,
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
    FROM
        takeaway_summary ts
        JOIN food_order fo_1 ON fo_1.order_number = ts.order_number::text
    WHERE
        ts.customer_id::text <> ALL (ARRAY['447448440754'::character varying::text, '447446933210'::character varying::text, '447919202938'::character varying::text])) existing
JOIN food_order fo ON fo.order_number = existing.order_number::text;

-- ---------------------------------------------------------------------------------------------
-- view v_admin_order_items
--   Order lines (order_item) with their order number and restaurant, for the dashboard order detail.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.v_admin_order_items AS
SELECT
    fo.order_number,
    fo.order_id,
    split_part(fo.order_number, '-'::text, 1) AS rest_ref,
    oi.product_name,
    oi.quantity,
    oi.price,
    oi.modifications
FROM
    order_item oi
    JOIN food_order fo ON fo.order_id = oi.order_id;

-- ---------------------------------------------------------------------------------------------
-- view v_admin_orders_daily
--   Per restaurant, local day and type: order count, gross and the restaurant's cut.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.v_admin_orders_daily AS
SELECT
    v_admin_orders.rest_ref,
    v_admin_orders.sort_day_local AS day,
    v_admin_orders.type,
    count(*) AS count,
    sum(v_admin_orders.total_price) AS gross,
    sum(v_admin_orders.rest_cost) AS your_cut
FROM
    v_admin_orders
GROUP BY
    v_admin_orders.rest_ref,
    v_admin_orders.sort_day_local,
    v_admin_orders.type;

-- ---------------------------------------------------------------------------------------------
-- view v_admin_orders_monthly
--   v_admin_orders_daily rolled up by month.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.v_admin_orders_monthly AS
SELECT
    v_admin_orders_daily.rest_ref,
    date_trunc('month'::text, v_admin_orders_daily.day::timestamp with time zone)::date AS month,
    v_admin_orders_daily.type,
    sum(v_admin_orders_daily.count)::bigint AS count,
    sum(v_admin_orders_daily.gross) AS gross,
    sum(v_admin_orders_daily.your_cut) AS your_cut
FROM
    v_admin_orders_daily
GROUP BY
    v_admin_orders_daily.rest_ref,
    (date_trunc('month'::text, v_admin_orders_daily.day::timestamp with time zone)::date),
    v_admin_orders_daily.type;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON VIEW public.v_admin_orders IS 'Delivery and takeaway orders as one list for the admin dashboard, with money and London-local day columns.';

COMMENT ON VIEW public.v_admin_order_items IS 'Order lines (order_item) with their order number and restaurant, for the dashboard order detail.';

COMMENT ON VIEW public.v_admin_orders_daily IS 'Per restaurant, local day and type: order count, gross and the restaurant''s cut.';

COMMENT ON VIEW public.v_admin_orders_monthly IS 'v_admin_orders_daily rolled up by month.';

-- Owner-rights views must not bypass the restricted source tables.
REVOKE ALL ON public.v_admin_orders, public.v_admin_order_items, public.v_admin_orders_daily, public.v_admin_orders_monthly FROM PUBLIC, anon, authenticated;

GRANT SELECT ON public.v_admin_orders, public.v_admin_order_items, public.v_admin_orders_daily, public.v_admin_orders_monthly TO service_role;
