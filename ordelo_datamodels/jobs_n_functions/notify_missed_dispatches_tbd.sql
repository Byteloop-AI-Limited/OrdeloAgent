----------------------------------------
-- notify_missed_dispatches - Identifies dispatches that have timed out and notifies the system
----------------------------------------
DROP FUNCTION IF EXISTS notify_missed_dispatches();
CREATE OR REPLACE FUNCTION notify_missed_dispatches()
RETURNS BOOLEAN AS $$
DECLARE
    response json;
    webhook_payload json;
    notified BOOLEAN := FALSE;
BEGIN
    WITH missed_dispatches AS (
        SELECT 
            dd.order_number,
            json_agg(json_build_object(
                'dispatch_id', d.dispatch_id,
                'rider_id', d.rider_id,
                'order_number', d.order_number,
                'order_status', dd.status,
                'dtts', d.dtts
            )) AS dispatches
        FROM delivery_dispatch d
        INNER JOIN delivery_detail dd ON d.order_number = dd.order_number
        WHERE d.status = 'accepted'
        -- AND DATE(d.dtts) = DATE(dd.dtts)
        AND dd.status = 'assigned'
        GROUP BY dd.order_number
    )
    SELECT 
        json_build_object(
            'missed_dispatches', (
                SELECT json_agg(row_to_json(md))
                FROM missed_dispatches md
            )
        ) INTO webhook_payload;
    
    -- Make the HTTP POST request with the payload
    response := (
        SELECT content 
        FROM http_post(
            'https://agent.ordelo.app/delivery-hooks/notify-missed-dispatches', 
            webhook_payload::text,
            'application/json'
        )
    );
    
    -- Log the response
    RAISE NOTICE 'Response from notify-missed-dispatches: %', response;
    notified := TRUE;
    
    RETURN notified;
END;
$$ LANGUAGE plpgsql;

-- Create the function to notify missed dispatches for an order
CREATE OR REPLACE FUNCTION notify_missed_dispatches_for_order(p_order_number VARCHAR(100))
RETURNS BOOLEAN AS $$
DECLARE
    response json;
    webhook_payload json;
    notified BOOLEAN := FALSE;
BEGIN
    WITH missed_dispatches AS (
        SELECT 
            dd.order_number,
            json_agg(json_build_object(
                'dispatch_id', d.dispatch_id,
                'rider_id', d.rider_id,
                'order_number', d.order_number,
                'order_status', dd.status,
                'dtts', d.dtts
            )) AS dispatches
        FROM delivery_dispatch d
        INNER JOIN delivery_detail dd ON d.order_number = dd.order_number
        WHERE d.status = 'accepted'
        AND dd.order_number = p_order_number
        -- AND DATE(d.dtts) = DATE(dd.dtts)
        AND dd.status = 'assigned'
        GROUP BY dd.order_number
    )
    SELECT 
        json_build_object(
            'missed_dispatches', (
                SELECT json_agg(row_to_json(md))
                FROM missed_dispatches md
            )
        ) INTO webhook_payload;
    
    -- Make the HTTP POST request with the payload
    response := (
        SELECT content 
        FROM http_post(
            'https://agent.ordelo.app/delivery-hooks/notify-missed-dispatches', 
            webhook_payload::text,
            'application/json'
        )
    );
    
    -- Log the response
    RAISE NOTICE 'Response from notify-missed-dispatches: %', response;
    notified := TRUE;
    
    RETURN notified;
END;
$$ LANGUAGE plpgsql;

------------
-- usage
select notify_missed_dispatches();
select notify_missed_dispatches_for_order('0f9d9e9b75fa4db7a1e34e0c53c6b986'); 
------------