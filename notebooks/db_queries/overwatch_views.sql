select * from delivery_summary where order_number='ELAS-ZXUV-21'; -- rest_ref, rest_confirmation_code, cust_confirmation_code, status, dtts as order_created_time, customer_id, customer_name, restaurant_confirmation_status, restaurant_update_dtts, pickup_time as scheduled_pickup_time
select * from delivery_detail order by dtts desc; -- vehicle_type, rider_id, rider_payout, distance, status_update_dtts (order_pickup time);
select * from delivery_dispatch where status='completed' and rider_id!='447448440754' order by status_update_dtts desc; -- vehicle_type, rider_id, rider_payout, distance, status_update_dtts (actual_pickup_time);

-- OrderSettlement
select 
final_order_value - total_customer_charge as food_value,
byteloop_commission_fee,
rest_cost,
total_customer_charge,
final_order_value,
driver_payout,
byteloop_commission_percentage as commission_rate,
breakdown::jsonb->>'profit' as profit,
breakdown::jsonb->>'payment_processing_fee' as payment_processing_fee,
breakdown::jsonb->>'payment_processing_fee' as payment_processing_fee,
* 
from delivery_option where order_number='ELAS-MSPI-21' and vehicle_type='car';

-- Delivery summary
select 
rest_ref,
rest_confirmation_code,
cust_confirmation_code,
status, 
dtts as order_created_time,
customer_id,
customer_name,
restaurant_confirmation_status,
pickup_time as scheduled_pickup_time
from delivery_summary where order_number='ELAS-ZXUV-21';

-- DeliveryDispatch
select  
rider_id,
vehicle_type,
status,
dtts as order_created_time,
order_number,
distance,
rider_payout
from delivery_dispatch where rider_id!='447448440754' and status='completed' order by status_update_dtts desc
;

-- Combined Overwatch View
WITH summary_cte AS (
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
    FROM delivery_summary
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
        breakdown::jsonb->>'profit' AS profit,
        breakdown::jsonb->>'payment_processing_fee' AS payment_processing_fee
    FROM delivery_option
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
FROM delivery_dispatch dd
JOIN summary_cte s ON dd.order_number = s.order_number AND dd.status = s.status
LEFT JOIN settlement_cte st ON dd.order_number = st.order_number AND dd.vehicle_type = st.vehicle_type
WHERE dd.rider_id != '447448440754'
  AND dd.status = 'completed'
ORDER BY s.order_created_time DESC;

-- Postgres function: Combined Overwatch View with optional order_numbers filter
-- If order_numbers is NULL or empty, default to latest 10 orders from delivery_dispatch.
CREATE OR REPLACE FUNCTION public.overwatch_view(order_numbers text[] DEFAULT NULL)
RETURNS TABLE (
    order_number text,
    rider_id text,
    vehicle_type text,
    status text,
    distance numeric,
    rider_payout numeric,
    rest_ref text,
    scheduled_pickup_time timestamptz,
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
    payment_processing_fee text
)
LANGUAGE sql
AS $$
WITH target_orders AS (
    SELECT unnest(order_numbers) AS order_number
    WHERE order_numbers IS NOT NULL AND array_length(order_numbers, 1) > 0
    UNION ALL
    SELECT dd.order_number
    FROM (
        SELECT order_number
        FROM delivery_dispatch
        WHERE (order_numbers IS NULL OR array_length(order_numbers, 1) IS NULL)
          AND status = 'completed'
          AND rider_id != '447448440754'
        ORDER BY status_update_dtts DESC
        LIMIT 10
    ) dd
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
    FROM delivery_summary
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
        breakdown::jsonb->>'profit' AS profit,
        breakdown::jsonb->>'payment_processing_fee' AS payment_processing_fee
    FROM delivery_option
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
FROM delivery_dispatch dd
JOIN target_orders t ON t.order_number = dd.order_number
JOIN summary_cte s ON dd.order_number = s.order_number AND dd.status = s.status
LEFT JOIN settlement_cte st ON dd.order_number = st.order_number AND dd.vehicle_type = st.vehicle_type
WHERE dd.rider_id != '447448440754' 
  AND dd.status = 'completed'
ORDER BY s.order_created_time DESC;
$$;
select * from overwatch_view();