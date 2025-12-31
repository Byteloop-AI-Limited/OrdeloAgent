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
    payment_processing_fee text,
    customer_email text,
    customer_house_number text,
    customer_building_name text,
    customer_street_name text,
    customer_city text,
    customer_postcode text,
    customer_lat numeric,
    customer_lon numeric,
    rider_name text,
    rider_vehicle_type text,
    rider_town text,
    rider_status text,
    rider_is_in_shift boolean,
    rider_priority integer,
    rider_shift_response_dtts timestamp
)
LANGUAGE sql
AS $$
WITH input_orders AS (
    SELECT unnest(order_numbers) AS order_number
    WHERE order_numbers IS NOT NULL AND array_length(order_numbers, 1) > 0
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
closed_orders AS (
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
        s.order_created_time
    FROM (
        SELECT *
        FROM delivery_dispatch
        WHERE status = 'completed'
          AND rider_id != '447448440754'
          AND (order_numbers IS NULL OR array_length(order_numbers, 1) IS NULL)
        ORDER BY status_update_dtts DESC
        LIMIT 10
    ) dd
    JOIN summary_cte s ON dd.order_number = s.order_number
    UNION ALL
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
        s.order_created_time
    FROM delivery_dispatch dd
    JOIN summary_cte s ON dd.order_number = s.order_number
    WHERE dd.status = 'completed'
      AND dd.rider_id != '447448440754'
      AND order_numbers IS NOT NULL
      AND array_length(order_numbers, 1) > 0
      AND dd.order_number IN (SELECT order_number FROM input_orders)
),
inflight_orders AS (
    SELECT
        di.order_number,
        di.rider_id,
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
        s.order_created_time
    FROM delivery_inflight di
    JOIN delivery_dispatch dd ON dd.dispatch_id = di.dispatch_id
    JOIN summary_cte s ON di.order_number = s.order_number
    WHERE (order_numbers IS NULL OR array_length(order_numbers, 1) IS NULL)
       OR di.order_number IN (SELECT order_number FROM input_orders)
),
base_orders AS (
    SELECT * FROM closed_orders
    UNION ALL
    SELECT * FROM inflight_orders
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
),
customer_cte AS (
    SELECT
        cust_id,
        cust_email,
        house_number,
        building_name,
        street_name,
        city,
        postcode,
        lat,
        lon
    FROM customer_master
),
rider_cte AS (
    SELECT
        rider_id,
        rider_name,
        vehicle_type AS rider_vehicle_type,
        town,
        status,
        is_in_shift,
        priority,
        shift_response_dtts
    FROM rider_master
)
SELECT 
    bo.order_number,
    bo.rider_id,
    bo.vehicle_type,
    bo.status,
    bo.distance,
    bo.rider_payout,
    bo.rest_ref,
    bo.scheduled_pickup_time,
    bo.restaurant_confirmation_status,
    bo.rest_confirmation_code,
    bo.cust_confirmation_code,
    bo.customer_id,
    bo.customer_name,
    st.food_value,
    st.byteloop_commission_fee,
    st.rest_cost,
    st.total_customer_charge,
    st.final_order_value,
    st.driver_payout,
    st.commission_rate,
    st.profit,
    st.payment_processing_fee,
    cust.cust_email AS customer_email,
    cust.house_number AS customer_house_number,
    cust.building_name AS customer_building_name,
    cust.street_name AS customer_street_name,
    cust.city AS customer_city,
    cust.postcode AS customer_postcode,
    cust.lat AS customer_lat,
    cust.lon AS customer_lon,
    rider.rider_name,
    rider.rider_vehicle_type,
    rider.town AS rider_town,
    rider.status AS rider_status,
    rider.is_in_shift AS rider_is_in_shift,
    rider.priority AS rider_priority,
    rider.shift_response_dtts AS rider_shift_response_dtts
FROM base_orders bo
LEFT JOIN settlement_cte st ON bo.order_number = st.order_number AND bo.vehicle_type = st.vehicle_type
LEFT JOIN customer_cte cust ON bo.customer_id = cust.cust_id
LEFT JOIN rider_cte rider ON bo.rider_id = rider.rider_id
ORDER BY bo.order_created_time DESC;
$$;
