select *
      FROM pgmq.read('owntracks', 5, 1000);

select job_process_owntracks();

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
from delivery_detail
order by dtts desc
limit 10;


select *
from delivery_detail
order by dtts desc
limit 10;


select *
from ordelo_config;


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

WITH inflight_missing_location AS (
        SELECT
            inflight.order_number,
            inflight.rider_id,
            MAX(location.dtts) as last_location_dtts,
			MAX(location.tst) AS tst
        FROM delivery_inflight inflight
        LEFT JOIN rider_location location
            ON inflight.order_number = location.order_number
            AND inflight.rider_id = location.rider_id
		GROUP BY inflight.order_number, inflight.rider_id
    )
select 
order_number,
rider_id,
tst,
current_timestamp,
current_timestamp - last_location_dtts as time_taken
from inflight_missing_location
where current_timestamp - last_location_dtts > (1|| ' minutes')::interval OR last_location_dtts IS NULL;
;
-- (interval_minutes || ' minutes')::interval

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

select DET.status as detail_status,
	dispatch.status as dispatch_status,
	DET.order_number
FROM delivery_detail as DET
left outer join delivery_dispatch as dispatch on DET.dispatch_id = dispatch.dispatch_id
order by DET.dispatch_id desc;


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


select job_assign_delivery();


SELECT public.job_assign_delivery();


select
from delivery_dispatch
left outer join rider_location
update DELIVERY_DETAIL
set STATUS='assigned' --set STATUS='completed'

where ORDER_NUMBER='faef370445774ab6aef91b6b1904470a';


select * from rider_location where order_number='ELAB-XBCL-21' order by dtts desc limit 100;