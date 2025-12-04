WITH deliverySnapShot AS (
    SELECT
      summ.order_number,
      summ.customer_id,
      det.vehicle_type   AS detail_vehicle_type,
      det.status         AS detail_vehicle_status,
      dopt.rank          AS available_vehicle_rank,
      dopt.vehicle_type  AS available_vehicle_type,
      summ.town,
      dopt.driver_payout,
      (dopt.breakdown::JSON ->> 'distance_miles')::DOUBLE precision as distance,
      rank() OVER (
        PARTITION BY summ.order_number
        ORDER BY det.status   ASC NULLS FIRST,
                 dopt.rank     ASC
      )                    AS next_vehicle_rank
    FROM delivery_summary summ
    inner JOIN delivery_option  dopt
      ON dopt.order_number = summ.order_number
    LEFT JOIN delivery_detail det
      ON det.order_number   = summ.order_number
     AND det.vehicle_type   = dopt.vehicle_type
    where summ.status        = 'unassigned'
  )
select * from deliverySnapShot;
-- Best approach to testing, let the init_delivery and process_delivery run with 15 sec intervals.
-- Check summary
select status,* from delivery_summary 
where order_number in ('WREN-HEHM-31', 'WREN-YKZT-20', 'WREN-YKZT-21') order by dtts desc;
-- Check detail
select status,* from delivery_detail where order_number in ('WREN-HEHM-31'
, 'WREN-YKZT-20', 'WREN-YKZT-21') order by order_number, dtts desc;
-- Check dispatch
select status,* from delivery_dispatch
where order_number in ('WREN-HEHM-31', 'WREN-YKZT-20', 'WREN-YKZT-21') order by order_number, dtts desc;
-- Check inflight
select * from delivery_inflight
where order_number in ('WREN-HEHM-31', 'WREN-YKZT-20', 'WREN-YKZT-21') order by dtts desc;

select process_delivery();
select job_create_dispatch();

select job_assign_dispatch();

select dispatch_complete_func(213);
-- cleanup for testing
delete from delivery_dispatch where order_number in ('WREN-HEHM-31', 'WREN-YKZT-20', 'WREN-YKZT-21');
delete from delivery_detail where order_number in ('WREN-HEHM-31', 'WREN-YKZT-20', 'WREN-YKZT-21');
delete from delivery_inflight where order_number in ('WREN-HEHM-31', 'WREN-YKZT-20', 'WREN-YKZT-21');
--update delivery_summary set status = 'unassigned' where order_number  in ('WREN-HEHM-31', 'WREN-YKZT-20', 'WREN-YKZT-21');
update delivery_summary set status = 'unassigned' where order_number  in ('WREN-HEHM-31');

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

select * from delivery_summary where order_number='ELAS-OROT-35';

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
