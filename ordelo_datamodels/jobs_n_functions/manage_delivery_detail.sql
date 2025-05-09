CREATE OR REPLACE FUNCTION manage_delivery_detail()
RETURNS TEXT AS $$
DECLARE
    rec RECORD;
    inserted_details TEXT := '';
    updated_orders TEXT := '';
    inserted_count INT := 0;
    updated_count INT := 0;
BEGIN
    -- insert delivery_detail records based on vehicle_types
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
        inserted_count := inserted_count + 1;
        IF inserted_details <> '' THEN
            inserted_details := inserted_details || E'\n';
        END IF;
        inserted_details := inserted_details || format('Inserted: order=%s, vehicle_type=%s, customer_id=%s', rec.order_number, rec.vehicle_type, rec.customer_id);
    END LOOP;
    -- timeout delivery_detail records
    -- timeout delivery_detail records
    WITH
    option_types AS (
        SELECT order_number, COUNT(DISTINCT vehicle_type) AS opt_count
        FROM delivery_option
        GROUP BY order_number
    ),
    timedout_types AS (
        SELECT order_number, COUNT(DISTINCT vehicle_type) AS det_count, MIN(dtts) AS min_dtts
        FROM delivery_detail
        WHERE status = 'vehicle_type_timedout'
        GROUP BY order_number
    ),
    eligible_orders AS (
        SELECT o.order_number, t.min_dtts
        FROM option_types o
        JOIN timedout_types t ON o.order_number = t.order_number
        WHERE o.opt_count = t.det_count
    ),
    updated AS (
        UPDATE delivery_detail dd
        SET status = 'timedout'
        FROM eligible_orders eo
        WHERE dd.order_number = eo.order_number
        AND dd.status = 'vehicle_type_timedout'
        AND CURRENT_TIMESTAMP - eo.min_dtts > INTERVAL '1 minutes'
        RETURNING dd.order_number
    )
    SELECT string_agg(DISTINCT format('Updated: order=%s', order_number), E'\n'), count(*)
    INTO updated_orders, updated_count
    FROM updated;

    -- Compose and return log
    RETURN format(
        'Inserted records (%s):%s%sUpdated orders (%s):%s%s',
        inserted_count,
        CASE WHEN inserted_count > 0 THEN E'\n' ELSE ' ' END,
        COALESCE(inserted_details, ''),
        updated_count,
        CASE WHEN updated_count > 0 THEN E'\n' ELSE ' ' END,
        COALESCE(updated_orders, '')
    );
END;
$$ LANGUAGE plpgsql;
