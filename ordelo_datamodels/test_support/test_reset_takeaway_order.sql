DROP FUNCTION IF EXISTS test_reset_takeaway_order(text);

CREATE OR REPLACE FUNCTION test_reset_takeaway_order(p_order_number text)
RETURNS TEXT AS $$
DECLARE
    v_summary_updated integer;
BEGIN
    -- Reset takeaway summary status to restaurant_unconfirmed
    UPDATE takeaway_summary
    SET 
    status = 'restaurant_unconfirmed', 
    restaurant_confirmation_status = 'restaurant_unconfirmed',
    pickup_time = NULL,
    dtts = current_timestamp
    WHERE order_number = p_order_number;
    GET DIAGNOSTICS v_summary_updated = ROW_COUNT;

    RETURN format(
        'Takeaway order %s reset (summary updated=%s)',
        p_order_number, v_summary_updated
    );
END;
$$ LANGUAGE plpgsql;

-- =============================================================================================
-- EXAMPLES AND OPERATOR SQL (commented out: applying this file never runs them; copy what you need)
-- =============================================================================================

-- select test_reset_takeaway_order('ELAS-AZML-22');

-- select * from takeaway_summary where order_number='ELAS-AZML-22';
