/**
Restaurant Confirmation Timeout Job

Purpose:
    - Automatically timeout restaurant_unconfirmed orders after configured duration
    - Support restaurant-specific timeout values via rest_ref parameter
    - Default prep time to 25 minutes on timeout
    - Transition order to 'unassigned' status to continue normal dispatch flow

Invocation:
    - Scheduled via pg_cron job (typically every minute)
    - Can be called with optional rest_ref parameter for restaurant-specific processing

Configuration:
    - Default timeout: ordelo_config.RESTAURANT_CONFIRMATION_TIMEOUT (default: 5 minutes)
    - Restaurant-specific: ordelo_config.{rest_ref}_RESTAURANT_CONFIRMATION_TIMEOUT
    - Example: 'WREN_RESTAURANT_CONFIRMATION_TIMEOUT' for WREN restaurant

Dependencies:
    - Reads from: delivery_summary, ordelo_config
    - Writes to: delivery_summary (status, restaurant_confirmation_status, restaurant_update_dtts, rest_prep_time_minutes, rest_confirmation_method, pickup_time)

Side Effects:
    - Updates delivery_summary status to 'unassigned'
    - Triggers downstream workflow (process_delivery will pick up these orders)

Parameters:
    - p_rest_ref (optional): Specific restaurant reference to process. If NULL, processes all timed-out orders.
**/

CREATE OR REPLACE FUNCTION job_restaurant_confirmation_timeout(p_rest_ref VARCHAR DEFAULT NULL)
RETURNS TABLE(action TEXT) LANGUAGE plpgsql AS $$
BEGIN
  RETURN QUERY
  WITH timeout_config AS (
    -- Get timeout value: restaurant-specific first, then default
    SELECT 
      ds.order_number,
      ds.rest_id,
      COALESCE(
        (SELECT config_value::NUMERIC 
         FROM ordelo_config 
         WHERE config_key = SPLIT_PART(ds.order_number, '-', 1) || '_RESTAURANT_CONFIRMATION_TIMEOUT'
         LIMIT 1),
        (SELECT config_value::NUMERIC 
         FROM ordelo_config 
         WHERE config_key = 'RESTAURANT_CONFIRMATION_TIMEOUT'
         LIMIT 1),
        5  -- Fallback to 5 minutes if no config found
      ) AS timeout_minutes
    FROM delivery_summary ds
    WHERE ds.status = 'restaurant_unconfirmed' or ds.status = 'restaurant_accept'
      AND (p_rest_ref IS NULL OR SPLIT_PART(ds.order_number, '-', 1) = p_rest_ref)
  ),
  timed_out_orders AS (
    UPDATE delivery_summary ds
    SET 
      status = 'unassigned',
      restaurant_confirmation_status = 'restaurant_timedout',
      restaurant_update_dtts = NOW(),
      rest_prep_time_minutes = 25,  -- Default to max time
      rest_confirmation_method = 'timeout',
      pickup_time = NOW() + INTERVAL '25 minutes'
    FROM timeout_config tc
    WHERE ds.order_number = tc.order_number
      AND (ds.status = 'restaurant_unconfirmed' OR ds.status = 'restaurant_accept')
      AND (EXTRACT(EPOCH FROM (NOW() - ds.dtts))/60) >= tc.timeout_minutes
    RETURNING 
      ds.order_number,
      ds.rest_id,
      tc.timeout_minutes,
      'Order ' || ds.order_number || ' → restaurant confirmation timed out after ' || tc.timeout_minutes || ' minutes, defaulted to 25min prep time' AS action
  )
  SELECT timed_out_orders.action FROM timed_out_orders;
END;
$$;

-- Example: Process specific restaurant
SELECT * FROM job_restaurant_confirmation_timeout('ELAS');

-- Example: Process all restaurants
-- SELECT * FROM job_restaurant_confirmation_timeout();
-- Show definition of this postgres function
-- SELECT pg_get_functiondef('job_restaurant_confirmation_timeout'::regproc);