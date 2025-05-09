CREATE OR REPLACE FUNCTION manage_delivery_detail()
RETURNS VOID AS $$
DECLARE
    rec RECORD;
BEGIN
    FOR rec IN
        SELECT order_number, vehicle_type, customer_id
        FROM (
            SELECT 
                dopt.order_number,
                dopt.vehicle_type,
                vto.customer_id,
                ROW_NUMBER() OVER (
                    PARTITION BY dopt.order_number
                    ORDER BY dopt.rank ASC
                ) AS next_vehicle_rank
            FROM (
                SELECT DISTINCT order_number, customer_id
                FROM delivery_detail
                WHERE status = 'vehicle_type_timedout'
            ) vto
            JOIN delivery_option dopt
                ON dopt.order_number = vto.order_number
            LEFT JOIN delivery_detail dd
                ON dopt.order_number = dd.order_number
                AND dopt.vehicle_type = dd.vehicle_type
            WHERE dd.vehicle_type IS NULL
        ) sub
        WHERE next_vehicle_rank = 1
    LOOP
        PERFORM insert_delivery_detail(rec.customer_id, rec.order_number, rec.vehicle_type);
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Function: init_delivery_detail
-- Description: Initializes delivery_detail for a given order_number and customer_id if not already present
CREATE OR REPLACE FUNCTION init_delivery_detail(order_number varchar, customer_id varchar)
RETURNS VOID AS $$
DECLARE
    v_vehicle_type varchar;
BEGIN
    -- Debug: Log the order_number being checked
    RAISE NOTICE 'Checking if order_number % exists in delivery_detail', init_delivery_detail.order_number;

    -- Check if order_number already exists in delivery_detail
    IF EXISTS (
        SELECT 1 FROM delivery_detail WHERE order_number = init_delivery_detail.order_number
    ) THEN
        RAISE NOTICE 'Order % already exists in delivery_detail. Skipping insert.', init_delivery_detail.order_number;
        RETURN;
    END IF;

    RAISE NOTICE 'Order % does not exist in delivery_detail. Proceeding to insert.', init_delivery_detail.order_number;

    -- Get vehicle_type from delivery_option with rank = 1
    SELECT vehicle_type INTO v_vehicle_type
    FROM delivery_option
    WHERE order_number = init_delivery_detail.order_number AND rank = 1
    LIMIT 1;

    -- Only insert if vehicle_type was found
    IF v_vehicle_type IS NOT NULL THEN
        PERFORM insert_delivery_detail(init_delivery_detail.customer_id, init_delivery_detail.order_number, v_vehicle_type);
    END IF;
END;
$$ LANGUAGE plpgsql;


-- drop function insert_delivery_detail(p_cust_id character varying, p_order_number character varying, p_vehicle_type vehicle_type_enum)