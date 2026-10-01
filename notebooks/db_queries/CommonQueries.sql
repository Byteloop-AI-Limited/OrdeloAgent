select * from thread order by dtts desc;
select * from restaurant_master;
-- commit;
select * from takeaway_summary order by dtts desc;
lkj;
'447741594995';
select * from thread where is_active=True order by dtts desc;
select * from get_latest_state_by_thread('ELAS-c8ce70f0-83a5-420c-ab9d-268c8060f11d');
select * from get_latest_state('447448440754', 'ORDELO');
select * from wa_location_observation;

select dtts, * from thread where agent='SFCS' and recipient not in ('447919202938', '447448440754', '447446933210') order by dtts desc;
select * from cust_rest_map where rest_ref='SFCS';
select * from thread where recipient='447341964134';
exclude_list = ['447919202938', '447448440754', '447446933210'];

-- delete from thread where recipient='447448440754';
-- 447427558868 - investigate threads for this rider.

select * from delivery_option where order_number like 'ELAS-DDJV-22%' order by id desc;
select * from delivery_dispatch where order_number like 'ELAS-XBKV-20%' ;
select * from delivery_summary where order_number like 'ELAS-%' order by dtts desc;
select * from customer_master;
select rest_ref, count(*) from cust_rest_map where has_consent group by rest_ref;
-- Check and close thread
select * from thread where is_active order by dtts desc;
update thread set is_active=False where is_active and recipient='447448440754';
--ELAS-c8ce70f0-83a5-420c-ab9d-268c8060f11d 
--ORDELO-7006a159-8f54-4615-ac0e-6fe58fed32c7

select * from thread where recipient='447427558868' order by dtts desc;
select * from delivery_dispatch where order_number='BNAT-NOLZ-21' order by dtts desc;
select * from cust_rest_map where cust_id='447448440754';
select * from customer_master where cust_id='447919202938';
select * from delivery_summary where order_number like 'SFCS-%'  order by dtts desc;
select * from delivery_summary order by dtts desc;
update delivery_summary set status='timedout' where order_number='SFCS-LSFC-25';


-- Cleanup of customer to simulate new customer
-- 447919202938
delete from cust_rest_map where cust_id='447919202938';
delete from customer_master where cust_id='447919202938';

select * from rider_pickup_alert;

update thread set is_active=false where is_active=True and dt<='2026-05-14' and agent='SFCS';
select * from thread where is_active=True and dt<'2026-03-27' order by dt desc;;
select distinct(payment_status) from food_order limit 100;
select * from rider_registrations order by inserted_at desc;

select pickup_time, * from delivery_summary where order_number='ELAS-ETXF-28';

SELECT dtts, dtts AT TIME ZONE 'Europe/London' as dtts_uk 
FROM delivery_summary 
WHERE order_number='ELAS-ETXF-27';

select * from delivery_dispatch  order by dtts desc;
select  dispatch_complete_func(1197);
select * from delivery_dispatch where status='completed' and rider_id!='447448440754' order by dtts desc ;
select * from delivery_summary order by dtts desc;
select SUBSTRING(phone, 2, LENGTH(phone)) as rider_id,* from rider_registrations;
447853175864
447909510536
447446933210
select rider_id,* from rider_registrations;

select * from delivery_option where order_number='BNAT-JXKN-22';

select * from delivery_summary order by dtts desc;

select * from customer_master where cust_id='447448440754';
select * from cust_rest_map where cust_id='447448440754';

delete from cust_rest_map where cust_id='447448440754';
delete from customer_master where cust_id='447448440754';
delete from cust_rest_map where cust_id='447448440754' and  rest_ref='SFCS';

update cust_rest_map set has_consent=false, consent_dtts='2026-01-09 23:42:32.030367+00' where cust_id='447448440754';
select * from customer_master order by dtts desc limit 10;
select *
      FROM pgmq.read('owntracks', 5, 1000);

select * from delivery_inflight;
select job_process_owntracks();
-- view definition of function - FUNCTION public.delivery_inflight_whook
select pg_get_functiondef('delivery_inflight_whook'::regproc);
select title, description, price, dietary_requirements from elas_menu;

select count(*) from rider_location_event;
select * from elas_menu_before_march;

-- delete from rider_master where rider_id in ('447448440754') and vehicle_type in ('electric_bike', 'scooter');

-- on postgresql, how to find if there are any triggers defined on the table delivery_summary?

select *
from pg_trigger
where tgrelid = 'delivery_summary'::regclass;

select * from restaurant_master;
select * from delivery_summary order by dtts desc limit 10;

select * from delivery_dispatch 
inner join rider_master on rider_master.rider_id = delivery_dispatch.rider_id
where order_number='ELAS-ZXUV-21';

select * from takeaway_summary order by dtts desc;
select * from delivery_summary where order_number='ELAS-ZXUV-21'; -- rest_ref, rest_confirmation_code, cust_confirmation_code, status, dtts as order_created_time, customer_id, customer_name, restaurant_confirmation_status, restaurant_update_dtts, pickup_time as scheduled_pickup_time
select * from delivery_detail order by dtts desc; -- vehicle_type, rider_id, rider_payout, distance, status_update_dtts (order_pickup time);
select * from delivery_dispatch where status='completed' and rider_id!='447448440754' order by status_update_dtts desc; -- vehicle_type, rider_id, rider_payout, distance, status_update_dtts (actual_pickup_time);

select final_order_value - total_customer_charge as food_value, * from delivery_option where order_number='BNAT-NOLZ-21' and vehicle_type='car';
select total_price-rest_cost as rest_savings, * from food_order where order_number='ELAS-HCTZ-20' limit 10;
select * from food_order order by order_dtts desc;
select 47.4-55.8;
{"profit": 1.32, "extra_fee": 0.0, "commission": 4.46, "rider_bonus": 0.14, "delivery_fee": 1.49, "driver_payout": 5.83, "distance_miles": 1.84, "service_charge": 2.0, "commission_rate": 0.15, "small_order_fee": 0.0, "final_order_value": 33.2, "total_customer_fee": 3.49, "service_charge_rate": 0.07, "payment_processing_fee": 0.79}
select status,
	rest_confirmation_code,
	cust_confirmation_code,
	current_timestamp - dtts as time_taken,
	*
from delivery_summary
order by dtts desc
limit 10;


select *
from delivery_dispatch
order by dtts desc
limit 10;


select *
from delivery_detail
where dispatch_id=937
order by dtts desc
limit 10;

update delivery_detail
set status='completed'
where dispatch_id=937;

-- Update delivery_summary status
UPDATE delivery_summary
SET status = 'completed'
WHERE order_number = 'ELAS-BBCH-21';


select *
from ordelo_config;


select *
from delivery_dispatch
order by dtts desc
limit 10;


select *
from delivery_dispatch
order by dtts desc
limit 10;


select *
from delivery_dispatch
order by dtts desc
limit 10;

-- Update delivery_inflight status
DELETE FROM delivery_inflight  
WHERE delivery_inflight.dispatch_id = 937;


select *
from delivery_inflight
order by dtts desc
limit 10;


select *
from delivery_option
where order_number like 'ELAS-YOJE-20'
order by id desc;

select * from food_order order by order_dtts desc;
--
select * from delivery_dispatch order by dtts desc limit 10;

select * from restaurant_master where rest_ref='ELAS';
update restaurant_master
set admins=Array['447448440754','447901518136','447914844933', '447446933210'] where rest_ref='ELAS';

select *
from delivery_option
limit 100;

select to_timestamp(tst), dtts, * 
from rider_location where order_number = 'WREN-DIOH-33' 
order by dtts desc
limit 5;

select *
from delivery_pricing_detail
limit 100;

-- Testing delivery
delete
from delivery_option
where order_number like 'WREN-TEST%';


delete
from delivery_pricing_detail
where order_number like 'WREN-TEST%';


delete
from delivery_summary
where order_number like 'WREN-TEST%';


delete
from delivery_detail
where order_number like 'WREN-TEST%';


delete
from delivery_dispatch
where order_number like 'WREN-TEST%';


delete
from delivery_inflight
where order_number like 'WREN-TEST%';


delete
from delivery_dispatch
where order_number like 'WREN-TEST%';


select *
from delivery_option
limit 100;

-- update order_number ELAB-KHEB-45 to WREN-TEST-01 FOR DELIVERY_option and delivery_pricing_detail

update delivery_pricing_detail
set order_number = 'WREN-TEST-01'
where order_number = 'ELAB-KHEB-45';

-- Inserting a test record required by /test to update.

insert into delivery_pricing_detail(order_number, distance, message)
update delivery_option
set order_number = 'WREN-TEST-01'
where order_number = 'ELAB-KHEB-45';


values('WREN-TEST-01', 0.83, 'Test message');


select *
from delivery_inflight
order by dtts desc
limit 10;


select *
from delivery_dispatch
order by dtts desc
limit 10;


delete
from delivery_inflight ;


select *
from dispatch_complete_func(2254);


select *
from rider_location
order by dtts desc
limit 100;


select *
from delivery_
select count(*)
from delivery_detail;

-- check queues

SELECT *
FROM pgmq_public.read('rider_dispatch_accepted');

-- Check current status

select status,
	order_number,
	current_timestamp - dtts,
	rider_id,
	dispatch_id
from delivery_detail
order by dtts desc
limit 10;


select dispatch_id,
	status,
	order_number,
	rider_id,
	dtts
from delivery_dispatch
order by dtts desc;

select *
from delivery_inflight
order by dtts desc;


where ORDER_NUMBER='faef370445774ab6aef91b6b1904470a';

SHOW statement_timeout;
select * from restaurant_master;
update restaurant_master set admins=Array['447424334783'] where rest_ref='ELAS';

select init_delivery('447448440754', 'ELAS-KDDV-21');

SELECT cleanup_delivery_order('ELAS-KDDV-21');

select order_number, status, pickup_time from delivery_summary order by dtts desc;

update delivery_summary set status='restaurant_unconfirmed', pickup_time=dtts where order_number='ELAS-KDDV-21';
update delivery_summary set status='restaurant_accept' where order_number='ELAS-KDDV-21';
update delivery_summary set status='restaurant_decline' where order_number='ELAS-KDDV-21';

select * from rider_location where order_number='ELAB-XBCL-21' order by dtts desc limit 100;

-- Drop the old constraint
ALTER TABLE delivery_summary 
DROP CONSTRAINT delivery_summary_status_check;

-- Add the updated constraint with new restaurant statuses
ALTER TABLE delivery_summary 
ADD CONSTRAINT delivery_summary_status_check 
CHECK (status IN (
    'restaurant_unconfirmed', 
    'restaurant_accept', 
    'restaurant_decline',
    'unassigned', 
    'timedout', 
    'assigned', 
    'completed'
));
ALTER TABLE delivery_summary 
ADD CONSTRAINT delivery_summary_status_check 
CHECK (status IN (
    'restaurant_unconfirmed', 
    'restaurant_accept', 
    'restaurant_decline',
    'unassigned', 
    'timedout', 
    'assigned', 
    'completed'
));

-- Or simpler viewdelivery_summary
SELECT * FROM pg_trigger WHERE tgname = 'trigger_restaurant_confirmation_request';

SELECT restaurant_confirmation_whook();
SHOW log_directory;
SHOW log_filename;


select * from thread order by dtts desc limit 10;
select * from delivery_summary order by dtts desc limit 10;

select * from delivery_detail where order_number='ELAS-ZSLI-22';
select * from delivery_inflight where order_number='ELAS-ZSLI-22';
select * from delivery_option where order_number='ELAS-ZSLI-22';
select * from delivery_dispatch where order_number='ELAS-ZSLI-22';

select * from delivery_detail order by dtts desc limit 10;

-- Testing fro wren
UPDATE food_order SET order_number = 'WREN-WWVP-26' WHERE order_number = 'ELAS-WWVP-26';
UPDATE order_item SET order_id = 'WWVP-26' WHERE order_id = 'WWVP-26';

INSERT INTO delivery_pricing_detail (order_number, distance, message)
SELECT 'WREN-WWVP-26', distance, message
FROM delivery_pricing_detail
WHERE order_number = 'ELAS-WWVP-26';

UPDATE delivery_option SET order_number = 'WREN-WWVP-26' WHERE order_number = 'ELAS-WWVP-26';

select * from delivery_option where order_number='ELAS-WWVP-26';

select pickup_time, dtts, restaurant_confirmation_status, status, * from delivery_summary;

select * from delivery_detail where order_number='ELAS-WWVP-26';


select * from rider_master where rider_id='447448440754';
delete from rider_master where rider_id='447448440754' and vehicle_type='bicycle';

-- Check outlier orders
select dtts, redispatch_dtts, * from delivery_summary where status='unassigned';
-- update delivery_summary set status='completed' where status='assigned';
-- update delivery_summary set status='completed' where order_number='ELAS-BYSW-21';

select * from delivery_detail where status='unassigned';
-- update delivery_detail set status='completed' where status='assigned';
select * from delivery_dispatch where rider_id is not null and status='assigned';
-- update delivery_dispatch set status='completed' where rider_id is not null and status='assigned';

select * from delivery_inflight;
-- delete from delivery_inflight where order_number='ELAS-BYSW-21';


-- Temp
select * from food_order where order_number='SFCS-CHFA-41';
select * from food_order where order_number='SFCS-SKVY-30';
select * from food_order where order_number like 'ELAS-%' and action='takeaway';


select 10.55 - (10.55 * 0.04 + .25);


SELECT pg_get_functiondef(oid)
  FROM pg_proc
  WHERE proname =
  'delivery_summary_timedout_whook'
    AND pronamespace = 'public'::regnamespace;

SELECT config_key, config_value FROM
  ordelo_config
  WHERE config_key LIKE
  '%DELIVERY_TIMEOUT_TIME';


update ordelo_config set config_value = '' where config_key = 'DELIVERY_TIMEOUT_TIME';
select * from waba_es order by dtts desc;


select dispatch_complete_func(1159);


select * from delivery_summary where order_number='SFCS-TVUC-20';

select * from delivery_dispatch where dispatch_id=1159;
select * from delivery_inflight;

select * from customer_master order by dtts desc;