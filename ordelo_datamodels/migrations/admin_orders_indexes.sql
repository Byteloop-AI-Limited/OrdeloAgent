-- Admin dashboard indexes
-- Apply these before admin_orders_views.sql.
-- In production, replace CREATE INDEX with CREATE INDEX CONCURRENTLY and run
-- each statement individually (CONCURRENTLY cannot run inside a transaction).

-- Keyset pagination + tenant filter on delivery_summary.
-- Supports: WHERE rest_ref = $1 AND (sort_time, order_number) < (...)
-- ORDER BY sort_time DESC, order_number DESC
CREATE INDEX IF NOT EXISTS idx_delivery_summary_admin_keyset
ON delivery_summary (
    rest_ref,
    (COALESCE(pickup_time, dtts)) DESC,
    order_number DESC
);

-- Functional index on London-local day for date-range filtering.
-- Supports: WHERE rest_ref = $1 AND sort_day_local BETWEEN $2 AND $3
CREATE INDEX IF NOT EXISTS idx_delivery_summary_admin_day_local
ON delivery_summary (
    rest_ref,
    ((COALESCE(pickup_time, dtts) AT TIME ZONE 'Europe/London')::date)
);

-- Same pair for takeaway_summary.
CREATE INDEX IF NOT EXISTS idx_takeaway_summary_admin_keyset
ON takeaway_summary (
    rest_ref,
    (COALESCE(pickup_time, dtts)) DESC,
    order_number DESC
);

CREATE INDEX IF NOT EXISTS idx_takeaway_summary_admin_day_local
ON takeaway_summary (
    rest_ref,
    ((COALESCE(pickup_time, dtts) AT TIME ZONE 'Europe/London')::date)
);

-- order_item is keyed by order_id (FK to food_order.order_id).
-- The items endpoint looks up items by order_id from a parent food_order row.
CREATE INDEX IF NOT EXISTS idx_order_item_order_id
ON order_item (order_id);

-- food_order.order_number is PK (implicit btree).
-- food_order.order_id is UNIQUE (implicit btree).
-- No further index required for the joins used in the admin views.
