select * from restaurant_master where rest_ref='ELAS';
update restaurant_master
set admins=Array['447448440754', '447446933210','447901518136','447914844933', '447917912646'] where rest_ref='ELAS';

select * from restaurant_master where rest_ref='ELAS';

update restaurant_master
set admins=Array['447448440754','447446933210', '447919202938'] where rest_ref='ELAS';

447914844933 - Unni
447901518136 - Bineesh
447917912646 - Dinesh
447448440754 - basal
447446933210 - rahul
447919202938 - bloop business account
447424334783 - Chaitra
;

select * from rider_master;
-- delete from rider_master where rider_id='447448440754' and vehicle_type!='car';
update rider_master
set vehicle_type = 'car', town='Salisbury'
where rider_id = '447424334783';

{"profit": 2.15, "extra_fee": 0.0, "commission": 5.1, "rider_bonus": 0.49, "delivery_fee": 1.49, "driver_payout": 5.5600000000000005, "distance_miles": 1.22, "service_charge": 2.0, "commission_rate": 0.15, "small_order_fee": 0.0, "final_order_value": 37.46, "total_customer_fee": 3.49, "service_charge_rate": 0.07, "payment_processing_fee": 0.88}