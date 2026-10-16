-- Definition taken from the live database on 2026-10-16 (the old repo copy is kept in _archive/_tbd_handle_restaurant_confirmation.sql).
CREATE OR REPLACE FUNCTION public.handle_restaurant_confirmation(p_order_number character varying, p_prep_time_minutes integer)
 RETURNS boolean
 LANGUAGE plpgsql
AS $function$
DECLARE
  v_updated BOOLEAN;
BEGIN
  -- Update delivery_summary
  UPDATE delivery_summary
  SET 
    status = 'unassigned',
    rest_confirmed_at = NOW(),
    rest_prep_time_minutes = p_prep_time_minutes,
    rest_confirmation_method = 'manual',
    pickup_time = NOW() + (p_prep_time_minutes || ' minutes')::INTERVAL
  WHERE order_number = p_order_number
    AND status = 'restaurant_unconfirmed'
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
$function$;
