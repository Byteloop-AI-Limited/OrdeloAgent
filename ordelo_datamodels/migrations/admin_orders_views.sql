-- Admin dashboard views
-- Run admin_orders_indexes.sql first.
-- All statements use CREATE OR REPLACE VIEW so this script is idempotent.

-- ============================================================================
-- v_admin_orders
-- One row per paid order, unioning delivery + takeaway summaries joined to
-- food_order financials.
--
-- Filtered out:
--   - Orders with no food_order row (pre-payment) via INNER JOIN
--   - Orders where rest_cost or commission_rate is NULL (data-quality gaps)
--
-- Derived columns:
--   sort_time        TIMESTAMPTZ  never null (dtts is NOT NULL on both tables)
--   pickup_day_local DATE         null when pickup_time is null (unconfirmed)
--   created_day_local DATE        never null
--   sort_day_local   DATE         never null; used for date-range filter + rollup
-- ============================================================================
CREATE OR REPLACE VIEW v_admin_orders AS
SELECT
    ds.order_number,
    ds.rest_ref,
    'delivery'::text                                              AS type,
    ds.status,
    ds.rest_confirmation_code,
    ds.pickup_time,
    ds.dtts                                                       AS created_at,
    ds.customer_name,
    (ds.pickup_time AT TIME ZONE 'Europe/London')::date           AS pickup_day_local,
    (ds.dtts AT TIME ZONE 'Europe/London')::date                  AS created_day_local,
    COALESCE(ds.pickup_time, ds.dtts)                             AS sort_time,
    (COALESCE(ds.pickup_time, ds.dtts) AT TIME ZONE 'Europe/London')::date
                                                                  AS sort_day_local,
    fo.total_price,
    fo.rest_cost,
    fo.commission_rate
FROM delivery_summary ds
JOIN food_order fo ON fo.order_number = ds.order_number
WHERE fo.rest_cost       IS NOT NULL
  AND fo.commission_rate IS NOT NULL

UNION ALL

SELECT
    ts.order_number,
    ts.rest_ref,
    'takeaway'::text                                              AS type,
    ts.status,
    ts.rest_confirmation_code,
    ts.pickup_time,
    ts.dtts                                                       AS created_at,
    ts.customer_name,
    (ts.pickup_time AT TIME ZONE 'Europe/London')::date           AS pickup_day_local,
    (ts.dtts AT TIME ZONE 'Europe/London')::date                  AS created_day_local,
    COALESCE(ts.pickup_time, ts.dtts)                             AS sort_time,
    (COALESCE(ts.pickup_time, ts.dtts) AT TIME ZONE 'Europe/London')::date
                                                                  AS sort_day_local,
    fo.total_price,
    fo.rest_cost,
    fo.commission_rate
FROM takeaway_summary ts
JOIN food_order fo ON fo.order_number = ts.order_number
WHERE 
  ts.customer_id NOT IN ('447448440754','447446933210', '447919202938');


-- ============================================================================
-- v_admin_order_items
-- One row per item line, scoped by rest_ref derived from order_number.
-- Powers the drill-down items endpoint.
-- modifications is TEXT[] → arrives as string[] over the Supabase JS client.
-- ============================================================================
CREATE OR REPLACE VIEW v_admin_order_items AS
SELECT
    fo.order_number,
    fo.order_id,
    split_part(fo.order_number, '-', 1)   AS rest_ref,
    oi.product_name,
    oi.quantity,
    oi.price,
    oi.modifications
FROM order_item oi
JOIN food_order fo ON fo.order_id = oi.order_id;


-- ============================================================================
-- v_admin_orders_daily
-- Pre-aggregated per (rest_ref, day, type).
-- "day" uses sort_day_local (Europe/London) for consistency with v_admin_orders
-- filtering — KPIs and the row list always cover the exact same set of orders.
-- Powers the /api/admin/orders/summary endpoint.
-- ============================================================================
CREATE OR REPLACE VIEW v_admin_orders_daily AS
SELECT
    rest_ref,
    sort_day_local          AS day,
    type,
    COUNT(*)                AS count,
    SUM(total_price)        AS gross,
    SUM(rest_cost)          AS your_cut
FROM v_admin_orders
GROUP BY rest_ref, sort_day_local, type;


-- ============================================================================
-- v_admin_orders_monthly
-- Roll-up of the daily view by London-local month-start.
-- Not consumed by OrdersView in v1 — reserved for a future Reports page.
-- Derive as: SELECT … FROM v_admin_orders_daily WHERE month BETWEEN $1 AND $2
-- ============================================================================
CREATE OR REPLACE VIEW v_admin_orders_monthly AS
SELECT
    rest_ref,
    date_trunc('month', day)::date   AS month,
    type,
    SUM(count)::bigint               AS count,
    SUM(gross)                       AS gross,
    SUM(your_cut)                    AS your_cut
FROM v_admin_orders_daily
GROUP BY rest_ref, date_trunc('month', day)::date, type;



-- select * from takeaway_summary where customer_id not in ('447448440754','447446933210') limit 10;
select * from v_admin_orders where rest_ref = 'ELAS' and type!='delivery' limit 100;


