"BNAT-REZF-20";
select pickup_time, dtts, restaurant_confirmation_status, status, * from delivery_summary where order_number='BNAT-REZF-20' ;
order_number='WREN-AEHO-21';
-- order_number='ELAS-OOLX-24';
select * from delivery_option where order_number='SFCS-JKRO-22';
select dtts, redispatch_dtts, status, * from delivery_summary where order_number='SFCS-JKRO-22';
-- 2026-05-31 22:26:44.261924+00	NULL	assignebyT
select * from delivery_summary order by dtts desc limit 10;

update delivery_detail set status='unassigned' where order_number='ELAS-XUDU-22';

select * from get_available_riders('ELAS-XUDU-22', 'dummy', 'car');

WITH availableRiders AS (
        SELECT 
            dd.order_number,
            gar.rider_id as rider_id_to_dispatch,
            gar.priority,
            dd.rider_payout,
            dd.distance,
            dd.vehicle_type,
            COUNT(gar.rider_id) as rider_count
        FROM delivery_detail dd
        LEFT JOIN LATERAL get_available_riders(dd.order_number, LOWER(dd.town), dd.vehicle_type) gar ON true
        WHERE dd.status = 'unassigned'
        GROUP BY dd.order_number, 
        dd.rider_payout, 
        dd.distance, 
        dd.vehicle_type, 
        gar.rider_id,
        gar.priority)
  select * from availableRiders;


select * from delivery_dispatch where order_number = 'ELAS-XUDU-22';
    WITH ridersToExclude AS (
        SELECT DISTINCT dDispatch.rider_id, dDispatch.vehicle_type
        FROM delivery_dispatch dDispatch
        WHERE dDispatch.order_number = 'ELAS-XUDU-22' 
        UNION 
        SELECT DISTINCT inflight.rider_id, 'inflight'
        FROM delivery_inflight inflight
    )
    SELECT 
        allRiders.rider_id,
        allRiders.priority
    FROM rider_master allRiders 
    WHERE 
    LOWER(allRiders.town)='dummy'
    AND allRiders.vehicle_type = 'car'
    AND allRiders.is_in_shift;
    AND NOT EXISTS 
    (SELECT 1 FROM ridersToExclude WHERE ridersToExclude.rider_id = allRiders.rider_id);

select status, restaurant_confirmation_status, * from delivery_summary 
where order_number like 'WREN-%';

-- Best approach to testing, let the init_delivery and process_delivery run with 15 sec intervals.
-- Check summary
select status,* from delivery_summary 
where order_number in ('WREN-AEHO-21') order by dtts desc;
-- Check detail
select status,* from delivery_detail where order_number in ('WREN-AEHO-21') order by order_number, dtts desc;
-- Check dispatch
select status,* from delivery_dispatch
where order_number in ('WREN-AEHO-21') order by order_number, dtts desc;
-- Check inflight
select * from delivery_inflight
where order_number in ('WREN-AEHO-21') order by dtts desc;

-- cleanup for testing
delete from delivery_dispatch where order_number in ('WREN-AEHO-21');
delete from delivery_detail where order_number in ('WREN-AEHO-21');
delete from delivery_inflight where order_number in ('WREN-AEHO-21');
--update delivery_summary set status = 'unassigned' where order_number  in ('WREN-HEHM-31', 'WREN-YKZT-20', 'WREN-YKZT-21');
update delivery_summary set status = 'unassigned' where order_number  in ('WREN-AEHO-21');

select process_delivery();
select job_create_dispatch();

select job_assign_dispatch();

select dispatch_complete_func(213);

delete from delivery_dispatch where order_number='WREN-YKZT-20' and vehicle_type='car';
delete from delivery_detail where order_number='WREN-YKZT-20' and vehicle_type='car';



update delivery_detail set status='unassigned' where order_number in ('WREN-HEHM-31','WREN-YKZT-20') and vehicle_type='bicycle';
update delivery_detail set status='vehicle_type_timedout' where order_number in ('WREN-HEHM-31','WREN-YKZT-20') and vehicle_type='bicycle';
update delivery_dispatch set status='accepted' where order_number in ('WREN-HEHM-31','WREN-YKZT-20') and vehicle_type='bicycle';

-- Update specific v_types
update delivery_detail 
set status='unassigned' 
--set status='vehicle_type_timedout' 
where order_number in ('WREN-HEHM-31','WREN-YKZT-20') and 
vehicle_type='bicycle'
;

-- Simulate scenarios
update delivery_detail set status='vehicle_type_timedout' where order_number in ('WREN-HEHM-31','WREN-YKZT-20', 'WREN-YKZT-21');
update delivery_detail set status='vehicle_type_timedout' where order_number in ('WREN-HEHM-31','WREN-YKZT-20') and vehicle_type='bicycle';


select status, * from delivery_summary where order_number  in ('WREN-HEHM-31', 'WREN-YKZT-20', 'WREN-YKZT-21');

-- Test if init delivery calles process_delivery as part of initialization
delete from delivery_summary where order_number='WREN-HEHM-31';
select init_delivery('447448440754','WREN-HEHM-31');


--  Testing restaurant confirmation
-- Cleaning up
select cleanup_delivery_order('ELAS-OROT-32');

select * from delivery_summary 
where order_number='ELAS-URXB-32';

update delivery_summary
set status='unassigned'
where order_number='ELAS-URXB-32';


update delivery_summary
set status='timedout'
where order_number='ELAS-URXB-32';

select status, pickup_time, * from delivery_summary 
where order_number='ELAS-OROT-35' 
order by dtts desc;


select * from food_order
where order_number='ELAS-OROT-35';

update delivery_summary
set status='restaurant_unconfirmed'
where order_number='ELAS-OROT-35';


update delivery_summary
set status='restaurant_accept'
where order_number='ELAS-OROT-32';

select * from food_order
where order_number='ELAS-OROT-32';
