-- =============================================================================================
-- ordelo_datamodels/_orphans/admin_dashboard.sql
-- Unused live object from the overwatch / admin area.
-- =============================================================================================
-- LIVE CHECK    matches the live database (2026-10-16). Orphan candidates: live, no caller found.
-- OBJECTS       fn     overwatch_view(order_numbers text[]) -> TABLE(order_number text, rider_id text, vehicle_type text, status text, distance numeric, rider_payout numeric, rest_ref text, scheduled_pickup_time timestamp with time zone, restaurant_confirmation_status text, rest_confirmation_code text, cust_confirmation_code text, customer_id text, customer_name text, food_value numeric, byteloop_commission_fee numeric, rest_cost numeric, total_customer_charge numeric, final_order_value numeric, driver_payout numeric, commission_rate numeric, profit text, payment_processing_fee text)
--                   Return delivery orders with status, confirmation status and latest dispatch for an overwatch view (optionally given order numbers).
-- REQUIRES      dispatch/delivery_dispatch.sql
--               delivery/delivery_option.sql
--               delivery/delivery_summary.sql
-- HOW TO RUN    Supabase SQL editor, whole file. Safe to re-run: CREATE ... IF NOT EXISTS / CREATE OR REPLACE / DROP ... IF EXISTS.
--               Apply the REQUIRES files first. No BEGIN/COMMIT: each statement stands alone.
-- SIDE EFFECTS  none when applied. Functions that make HTTP calls or change rows only do so if someone calls them.
-- HOW IT FITS   Orphan candidates (Gate 1 decision D1): objects that exist on live but that nothing calls. A search on 2026-10-16 found
--                 no reference in OrdeloAgent, restaurant-frontend or restaurant-agents code, in any other live function or view, in a
--                 trigger or in a pg_cron job. They are captured here exactly as live so the repo describes the whole database.
--                 Nothing has been dropped: deciding keep or drop is an owner decision (docs/to-do.md). Before dropping one, re-check
--                 for callers outside these three repos (other services, manual scripts, Supabase Studio).
-- LIFECYCLE     none
-- CALLED BY     overwatch_view:
--                 nothing found (no code, trigger, cron job or other SQL refers to it)
-- PYTHON MODEL  none
-- SECURITY      overwatch_view(): executable by PUBLIC (default)
-- TESTS         none
-- GOTCHAS       none
-- SEE ALSO      docs/to-do.md (decide on orphan candidates)
-- =============================================================================================

-- ---------------------------------------------------------------------------------------------
-- function overwatch_view(order_numbers text[]) -> TABLE(order_number text, rider_id text, vehicle_type text, status text, distance numeric, rider_payout numeric, rest_ref text, scheduled_pickup_time timestamp with time zone, restaurant_confirmation_status text, rest_confirmation_code text, cust_confirmation_code text, customer_id text, customer_name text, food_value numeric, byteloop_commission_fee numeric, rest_cost numeric, total_customer_charge numeric, final_order_value numeric, driver_payout numeric, commission_rate numeric, profit text, payment_processing_fee text)
--   Return delivery orders with status, confirmation status and latest dispatch for an overwatch view (optionally given order numbers).
--   Data: reads delivery_dispatch, delivery_option, delivery_summary.
-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.overwatch_view (order_numbers text[] DEFAULT NULL::text[])
    RETURNS TABLE (
        order_number text,
        rider_id text,
        vehicle_type text,
        status text,
        distance numeric,
        rider_payout numeric,
        rest_ref text,
        scheduled_pickup_time timestamp with time zone,
        restaurant_confirmation_status text,
        rest_confirmation_code text,
        cust_confirmation_code text,
        customer_id text,
        customer_name text,
        food_value numeric,
        byteloop_commission_fee numeric,
        rest_cost numeric,
        total_customer_charge numeric,
        final_order_value numeric,
        driver_payout numeric,
        commission_rate numeric,
        profit text,
        payment_processing_fee text)
    LANGUAGE sql
    AS $function$
    WITH target_orders AS (
        SELECT
            unnest(order_numbers) AS order_number
        WHERE
            order_numbers IS NOT NULL
            AND array_length(order_numbers, 1) > 0
        UNION ALL
        SELECT
            dd.order_number
        FROM (
            SELECT
                order_number
            FROM
                delivery_dispatch
            WHERE (order_numbers IS NULL
                OR array_length(order_numbers, 1) IS NULL)
            AND status = 'completed'
            AND rider_id != '447448440754'
        ORDER BY
            status_update_dtts DESC
        LIMIT 10) dd
),
summary_cte AS (
    SELECT
        order_number,
        rest_ref,
        rest_confirmation_code,
        cust_confirmation_code,
        status,
        dtts AS order_created_time,
        customer_id,
        customer_name,
        restaurant_confirmation_status,
        pickup_time AS scheduled_pickup_time
    FROM
        delivery_summary
),
settlement_cte AS (
    SELECT
        order_number,
        vehicle_type,
        final_order_value - total_customer_charge AS food_value,
        byteloop_commission_fee,
        rest_cost,
        total_customer_charge,
        final_order_value,
        driver_payout,
        byteloop_commission_percentage AS commission_rate,
        breakdown::jsonb ->> 'profit' AS profit,
        breakdown::jsonb ->> 'payment_processing_fee' AS payment_processing_fee
    FROM
        delivery_option
)
SELECT
    dd.order_number,
    dd.rider_id,
    dd.vehicle_type,
    dd.status,
    dd.distance,
    dd.rider_payout,
    s.rest_ref,
    s.scheduled_pickup_time,
    s.restaurant_confirmation_status,
    s.rest_confirmation_code,
    s.cust_confirmation_code,
    s.customer_id,
    s.customer_name,
    st.food_value,
    st.byteloop_commission_fee,
    st.rest_cost,
    st.total_customer_charge,
    st.final_order_value,
    st.driver_payout,
    st.commission_rate,
    st.profit,
    st.payment_processing_fee
FROM
    delivery_dispatch dd
    JOIN target_orders t ON t.order_number = dd.order_number
    JOIN summary_cte s ON dd.order_number = s.order_number
        AND dd.status = s.status
    LEFT JOIN settlement_cte st ON dd.order_number = st.order_number
        AND dd.vehicle_type = st.vehicle_type
WHERE
    dd.rider_id != '447448440754'
    AND dd.status = 'completed'
ORDER BY
    s.order_created_time DESC;
$function$;

-- ---------------------------------------------------------------------------------------------
-- Database comments (COMMENT ON): the one-line descriptions above, stored in the catalogue so Supabase Studio
-- shows them. Applied to live only with owner approval (plan Gate 2); until then they exist only in this file.
-- ---------------------------------------------------------------------------------------------
COMMENT ON FUNCTION public.overwatch_view (order_numbers text[]) IS 'Return delivery orders with status, confirmation status and latest dispatch for an overwatch view (optionally given order numbers).';
