select dtts,* from rider_location order by dtts desc limit 100;
select * from rider_location_event order by dtts desc limit 100;

select * from delivery_dispatch limit 10;
select * from delivery_inflight limit 10;

-- owntracks/447448440754/447448440754-ELAS-FRGJ-29
INSERT INTO rider_location_event (topic, rider_id, customer_id, order_number, rid, event, dt, dtts)
VALUES (
    'owntracks/447448440754/447448440754-ELAS-FRGJ-29/event',
    '447448440754',
    '447448440754',
    'ELAS-FRGJ-29',
    'cust',
    -- 'rest',
    'enter',
    '2025-10-16',
    '2025-10-16 14:37:00.315655+00'
);

delete from rider_location_event where order_number = 'ELAS-FRGJ-29';

SELECT config_value 
FROM ordelo_config
WHERE config_key = 'ORDELO_APP_URL';