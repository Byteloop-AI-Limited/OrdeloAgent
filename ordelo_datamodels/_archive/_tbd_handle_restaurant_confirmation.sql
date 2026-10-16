/**
Handle Restaurant Confirmation

Purpose:
    - Process manual restaurant confirmation of food preparation time
    - Update delivery_summary with confirmed prep time
    - Calculate pickup_time based on prep time
    - Transition order to 'unassigned' status to trigger dispatch flow
    - Eagerly call process_delivery() to start dispatch creation

Invocation:
    - Called via Supabase RPC from FastAPI endpoint
    - Triggered by WhatsApp callback when restaurant confirms prep time

Parameters:
    - p_order_number: The order number to confirm
    - p_prep_time_minutes: Restaurant's confirmed prep time (5, 15, or 25 minutes)

Dependencies:
    - Reads from: delivery_summary
    - Writes to: delivery_summary (status, restaurant_confirmation_status, restaurant_update_dtts, rest_prep_time_minutes, rest_confirmation_method, pickup_time)
    - Calls: process_delivery()

Returns:
    - BOOLEAN: TRUE if update successful, FALSE if order not found or already confirmed

Side Effects:
    - Updates delivery_summary status to 'unassigned'
    - Calls process_delivery() to create delivery_detail records
    - Triggers downstream dispatch creation workflow
**/

CREATE OR REPLACE FUNCTION handle_restaurant_confirmation(
  p_order_number VARCHAR,
  p_prep_time_minutes INTEGER
)
RETURNS BOOLEAN AS $$
DECLARE
  v_updated BOOLEAN;
BEGIN
  -- Update delivery_summary
  UPDATE delivery_summary
  SET 
    status = 'unassigned',
    restaurant_confirmation_status = 'restaurant_accept',
    restaurant_update_dtts = NOW(),
    rest_prep_time_minutes = p_prep_time_minutes,
    rest_confirmation_method = 'manual',
    pickup_time = NOW() + (p_prep_time_minutes || ' minutes')::INTERVAL
  WHERE order_number = p_order_number
    AND restaurant_confirmation_status = 'restaurant_unconfirmed'
  RETURNING TRUE INTO v_updated;
  
  IF v_updated THEN
    -- Trigger process_delivery for this order
    PERFORM process_delivery();
    RAISE NOTICE 'Restaurant confirmed % minutes for order %', p_prep_time_minutes, p_order_number;
    RETURN TRUE;
  ELSE
    RAISE NOTICE 'Order % not found or already confirmed', p_order_number;
    RETURN FALSE;
  END IF;
END;
$$ LANGUAGE plpgsql;

-- Example usage:
-- SELECT handle_restaurant_confirmation('WREN-12345', 15);
