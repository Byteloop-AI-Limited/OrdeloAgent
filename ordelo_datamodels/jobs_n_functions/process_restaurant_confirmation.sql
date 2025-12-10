/**
Restaurant Confirmation Timeout Management

Purpose:
    - Automatically timeout restaurant confirmations that have not received a pickup_time selection.
    - Orders where restaurant_confirmation_status is 'restaurant_accept' but pickup_time is still NULL
      after the configured timeout interval are transitioned to 'restaurant_timedout'.
    - This triggers the webhook `_handle_restaurant_timedout` in delivery_hooks.py via the
      `trigger_restaurant_updates` trigger on restaurant_confirmation_status changes.

Invocation:
    - Scheduled via pg_cron job every 5 seconds.
    - Example:SELECT * FROM process_restaurant_confirmation();

Configuration:
    - Restaurant-specific timeout: ordelo_config.{rest_ref}_RESTAURANT_CONFIRMATION_TIMEOUT_TIME
    - Default timeout: ordelo_config.RESTAURANT_CONFIRMATION_TIMEOUT_TIME
    - Fallback: 5 minutes if no config found
    - Example config key: 'ELAS_RESTAURANT_CONFIRMATION_TIMEOUT_TIME' for ELAS restaurant

Dependencies:
    - Reads from: delivery_summary, ordelo_config
    - Writes to: delivery_summary (restaurant_confirmation_status, restaurant_update_dtts)

Side Effects:
    1. Updates restaurant_confirmation_status to 'restaurant_timedout' for timed-out orders.
    2. Sets restaurant_update_dtts to current timestamp.
    3. Triggers `trigger_restaurant_updates` which calls `/delivery-hooks/restaurant-confirmation-request`
       with trigger_reason='restaurant_timedout'.
    4. The webhook handler `_handle_restaurant_timedout` in delivery_hooks.py processes the timeout.

Timeout Conditions:
    - restaurant_confirmation_status = 'restaurant_unconfirmed' OR 'restaurant_accept'
    - pickup_time IS NULL (restaurant hasn't selected a prep time yet)
    - Time since dtts exceeds configured timeout interval

See also:
    - docs/restaurant_confirmation_flow.md for the full restaurant confirmation journey.
    - watomation/routers/delivery_hooks.py for the webhook handler.
    - ordelo_datamodels/summary.sql for the trigger definition.
**/

CREATE OR REPLACE FUNCTION process_restaurant_confirmation() 
RETURNS TABLE(action TEXT) 
LANGUAGE plpgsql AS $$
BEGIN
  RETURN QUERY
  WITH timedout_confirmations AS (
    -- Update orders where restaurant hasn't completed confirmation in time
    UPDATE delivery_summary ds
    SET 
      restaurant_confirmation_status = 'restaurant_timedout',
      restaurant_update_dtts = NOW()
    WHERE ds.restaurant_confirmation_status IN ('restaurant_unconfirmed', 'restaurant_accept')
      AND ds.pickup_time IS NULL
      AND (EXTRACT(EPOCH FROM (NOW() - ds.dtts)) / 60) > COALESCE(
          (SELECT config_value::numeric FROM ordelo_config 
           WHERE config_key = ds.rest_ref || '_RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1),
          (SELECT config_value::numeric FROM ordelo_config 
           WHERE config_key = 'RESTAURANT_CONFIRMATION_TIMEOUT_TIME' LIMIT 1),
          5  -- fallback to 5 minutes if no config found
      )
    RETURNING
      ds.order_number,
      ds.rest_ref,
      ds.restaurant_confirmation_status,
      'Order ' || ds.order_number || ' (' || ds.rest_ref || ') → restaurant_confirmation_status set to restaurant_timedout' AS action
  )
  SELECT tc.action FROM timedout_confirmations tc;
END;
$$;

-- Schedule this function to run every 5 seconds via pg_cron
-- SELECT cron.schedule('process_restaurant_confirmation', '*/5 * * * * *', 'SELECT * FROM process_restaurant_confirmation()');

-- To unschedule:
-- SELECT cron.unschedule('process_restaurant_confirmation');

-- Manual test:
SELECT * FROM process_restaurant_confirmation();
