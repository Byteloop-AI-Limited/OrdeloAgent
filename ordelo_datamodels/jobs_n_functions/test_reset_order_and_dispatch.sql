DROP FUNCTION IF EXISTS test_reset_order_and_dispatch(text);
CREATE OR REPLACE FUNCTION test_reset_order_and_dispatch(p_order_number text)
RETURNS TEXT AS $$
DECLARE
    v_inflight_deleted integer;
    v_dispatch_deleted integer;
    v_detail_deleted integer;
    v_summary_updated integer;
BEGIN
    -- Delete inflight rows for the order
    DELETE FROM delivery_inflight
    WHERE order_number = p_order_number;
    GET DIAGNOSTICS v_inflight_deleted = ROW_COUNT;

    -- Delete dispatch rows for the order
    DELETE FROM delivery_dispatch
    WHERE order_number = p_order_number;
    GET DIAGNOSTICS v_dispatch_deleted = ROW_COUNT;

    -- Delete delivery detail rows for the order
    DELETE FROM delivery_detail
    WHERE order_number = p_order_number;
    GET DIAGNOSTICS v_detail_deleted = ROW_COUNT;

    -- Reset summary status to unassigned; Bypass rest confirmation
    UPDATE delivery_summary
    SET 
    status = 'unassigned', 
    restaurant_confirmation_status = 'auto_accept',
    pickup_time = current_timestamp + interval '10 minutes',
    dtts = current_timestamp
    WHERE order_number = p_order_number;
    GET DIAGNOSTICS v_summary_updated = ROW_COUNT;

    RETURN format(
        'Order %s reset (inflight deleted=%s, dispatch deleted=%s, detail deleted=%s, summary updated=%s)',
        p_order_number, v_inflight_deleted, v_dispatch_deleted, v_detail_deleted, v_summary_updated
    );
END;
$$ LANGUAGE plpgsql;

select test_reset_order_and_dispatch('ELAS-ZVEO-29');
----------------------------------------
-- TimeoutUnassignedDispatch
----------------------------------------
UPDATE delivery_dispatch 
SET status = 'timedout' 
WHERE status = 'unassigned'
AND (current_timestamp - dtts) > interval '30 seconds';
