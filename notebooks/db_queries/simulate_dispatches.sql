select * from delivery_summary where order_number='ELAS-OOLX-24' order by dtts desc limit 10;
select * from delivery_dispatch where order_number='ELAS-OOLX-24' order by dtts desc limit 10;

INSERT INTO delivery_dispatch (order_number, rider_id, rider_payout, distance, vehicle_type, status)
VALUES ('ELAS-OOLX-24', '447469849539', 5.92, 1.14, 'car', 'unassigned');

select * from customer_master;

select * from delivery_dispatch where order_number='ELAS-OOLX-24' order by dtts desc limit 10;

delete from delivery_dispatch where order_number='ELAS-OOLX-24' and rider_id='447446933210';