-- Function: init_delivery_detail
-- Description: Initializes delivery_detail for a given order_number and customer_id if not already present
CREATE OR REPLACE FUNCTION init_delivery_detail(p_order_number varchar, p_customer_id varchar)
RETURNS text AS $$
DECLARE
    v_vehicle_type varchar;
BEGIN
    -- Debug: Log the order_number being checked (now as return value)
    -- Check if order_number already exists in delivery_detail
    IF EXISTS (
        SELECT 1 FROM delivery_detail WHERE order_number = p_order_number
    ) THEN
        RETURN format('Order %s already exists in delivery_detail. Skipping insert.', p_order_number);
    END IF;

    -- Get vehicle_type from delivery_option with rank = 1
    SELECT vehicle_type INTO v_vehicle_type
    FROM delivery_option
    WHERE order_number = p_order_number AND rank = 1
    LIMIT 1;

    IF v_vehicle_type IS NULL THEN
        RETURN format('Order %s does not exist in delivery_detail, but no vehicle_type with rank=1 found in delivery_option.', p_order_number);
    END IF;

    PERFORM insert_delivery_detail(p_customer_id, p_order_number, v_vehicle_type);
    RETURN format('Order %s did not exist in delivery_detail. Inserted with vehicle_type %s.', p_order_number, v_vehicle_type);
END;
$$ LANGUAGE plpgsql;


-- drop function insert_delivery_detail(p_cust_id character varying, p_order_number character varying, p_vehicle_type vehicle_type_enum)