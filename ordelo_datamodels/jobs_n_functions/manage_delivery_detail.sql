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

-- drop function insert_delivery_detail(p_cust_id character varying, p_order_number character varying, p_vehicle_type vehicle_type_enum)