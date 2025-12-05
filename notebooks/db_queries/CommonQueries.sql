select *
      FROM pgmq.read('owntracks', 5, 1000);

select job_process_owntracks();
-- view definition of function - FUNCTION public.delivery_inflight_whook
select pg_get_functiondef('delivery_inflight_whook'::regproc);

select count(*) from rider_location_event;

select *
from rider_master
limit 2;

-- on postgresql, how to find if there are any triggers defined on the table delivery_summary?

select *
from pg_trigger
where tgrelid = 'delivery_summary'::regclass;


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
where order_number like 'WREN-TEST-%'
order by id desc;

--

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

-- Or simpler view
\d delivery_summary
SELECT * FROM pg_trigger WHERE tgname = 'trigger_restaurant_confirmation_request';

SELECT restaurant_confirmation_whook();
SHOW log_directory;
SHOW log_filename;


select * from delivery_summary where order_number='ELAS-ZVEO-29';