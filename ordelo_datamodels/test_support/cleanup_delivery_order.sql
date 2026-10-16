/**
Cleanup Delivery Order – Testing and Maintenance Utility

Purpose:
    - Deletes all records associated with a specific order number from the delivery workflow tables.
    - Used for testing, cleanup, and maintenance purposes.
    - WARNING: This is a destructive operation and should be used with caution.

Invocation:
    - Called manually for testing purposes to clean up test orders.
    - Called by maintenance scripts to remove old/invalid orders.
    - Should NOT be used in production workflows without proper authorization.

Dependencies:
    - Reads from: `delivery_detail` (to verify order exists).
    - Writes to: `delivery_summary`, `delivery_detail`, `delivery_dispatch`, `delivery_inflight` (delete).

Side Effects:
    1. Permanently removes all records for the specified order from all delivery tables.
    2. Cascades deletion across dispatch, detail, and summary tables.
    3. Removes any inflight records associated with the order.

Parameters:
    - p_order_number: The order number to clean up (e.g., 'ORD-123456').

Returns:
    - Success message with order number and count of deleted records.
    - Error message if order not found.

See also: dispatch_complete_func.sql for the completion workflow.
**/

----------------------------------------
-- cleanupDeliveryOrder - Deletes all records for an order
----------------------------------------
DROP FUNCTION IF EXISTS cleanup_delivery_order(text);

CREATE OR REPLACE FUNCTION cleanup_delivery_order(p_order_number text)
RETURNS TEXT AS $$
DECLARE
    v_dispatch_count INTEGER;
    v_detail_count INTEGER;
    v_summary_count INTEGER;
    v_inflight_count INTEGER;
    v_total_count INTEGER;
BEGIN
    -- Check if order exists
    IF NOT EXISTS (SELECT 1 FROM delivery_summary WHERE order_number = p_order_number) THEN
        RETURN 'Order ' || p_order_number || ' not found';
    END IF;

    -- Delete from delivery_inflight (must be first due to foreign key constraints)
    DELETE FROM delivery_inflight
    WHERE dispatch_id IN (
        SELECT dispatch_id 
        FROM delivery_detail 
        WHERE order_number = p_order_number
    );
    GET DIAGNOSTICS v_inflight_count = ROW_COUNT;

    -- Delete from delivery_dispatch
    DELETE FROM delivery_dispatch where order_number = p_order_number;
    
    -- Delete from delivery_detail
    DELETE FROM delivery_detail
    WHERE order_number = p_order_number;
    GET DIAGNOSTICS v_dispatch_count = ROW_COUNT;

    -- Delete from delivery_detail
    DELETE FROM delivery_detail
    WHERE order_number = p_order_number;
    GET DIAGNOSTICS v_detail_count = ROW_COUNT;

    -- Delete from delivery_summary
    DELETE FROM delivery_summary
    WHERE order_number = p_order_number;
    GET DIAGNOSTICS v_summary_count = ROW_COUNT;

    -- Calculate total deletions
    v_total_count := v_inflight_count + v_dispatch_count + v_detail_count + v_summary_count;

    RETURN 'Order ' || p_order_number || ' cleaned up. Deleted: ' || 
           v_summary_count || ' summary, ' || 
           v_detail_count || ' detail, ' || 
           v_dispatch_count || ' dispatch, ' || 
           v_inflight_count || ' inflight records. Total: ' || v_total_count;
END;
$$ LANGUAGE plpgsql;
