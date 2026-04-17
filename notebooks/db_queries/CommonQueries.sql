select * from thread order by dtts desc;
select * from thread where is_active order by dtts desc;

update thread set is_active=False where is_active and recipient='447448440754';


select * from delivery_dispatch order by dtts desc;
-- update thread set is_active=false where is_active=True and dt<='2026-03-27';
select * from thread where is_active=True and dt<'2026-03-27' order by dt desc;;
select * from food_order limit 1;
select * from rider_registrations order by inserted_at desc;

select pickup_time, * from delivery_summary where order_number='ELAS-ETXF-28';

SELECT dtts, dtts AT TIME ZONE 'Europe/London' as dtts_uk 
FROM delivery_summary 
WHERE order_number='ELAS-ETXF-27';

select * from delivery_dispatch  where status like '%pick%' order by dtts desc;

select * from delivery_dispatch where status='completed' and rider_id!='447448440754' order by dtts desc ;
select * from delivery_summary order by dtts desc;
select SUBSTRING(phone, 2, LENGTH(phone)) as rider_id,* from rider_registrations;
447853175864
447909510536
447446933210
select rider_id,* from rider_registrations;

select * from delivery_option where order_number='ELAS-LORN-24';

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

select final_order_value - total_customer_charge as food_value, * from delivery_option where order_number='ELAS-MSPI-21' and vehicle_type='car';
select total_price-rest_cost as rest_savings, * from food_order where order_number='ELAS-HCTZ-20' limit 10;
select * from food_order where order_number='ELAS-OKKS-20' limit 10;
select 47.4-55.8;

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
order by dtts desc
limit 10;


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

ELAS-ZSLI-22
select * from delivery_detail order by dtts desc limit 10;
-- ELAS-WWVP-26
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


ELAS-ffed1547-da76-426d-8f6a-83aec8573a0e
ELAS-ea98ad6f-b886-485d-a9c8-1cf1cfefa76c
SFCS-cb4795de-e1dc-41e6-81a3-4146df1b3bc8
ELAS-36d3c485-9bea-4cd7-ae96-f4d68552c5ec
ELAS-09888d8f-c7ac-4733-8d3b-c31340a3ce17
ELAS-e8606e55-599a-4858-8a8a-59f24d56c078
ELAS-c4982124-380c-4679-848d-7dd1eb6507c1
ELAS-368da687-7ccd-48d5-b447-b039f282c76c
ELAS-934b9f8d-dcfd-4956-ad5c-aff8381666fa
ELAS-b14038b1-ceb2-4778-9ee9-dd7ab200c294
ELAS-be68d7b6-2f55-4afd-9e5e-c869220ec6a8
ELAS-24eaa243-dc18-4ba4-ae75-c3a56ca5e189
INDI-7832ab4a-646d-4f79-ae07-0c13b3e0fd1d
ELAS-ab419d0e-803a-4118-bbca-b605064b9a7e
ELAS-6072eff6-ae7e-43b3-ba65-eba56429963f
ELAS-54ab221d-0e44-43cf-8c17-7d83ff1df82f