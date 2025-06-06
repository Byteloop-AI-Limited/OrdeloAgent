-- Testing manage dd and init dd

select * from delivery_detail order by dtts desc;
select * from delivery_pricing_detail where order_number ='WREN-RQGI-29';
update delivery_pricing_detail set

-- debug
select status, CURRENT_TIMESTAMP - dtts, * from delivery_detail 
order by dtts desc;


select * from restaurant_master;

select public.job_create_dispatch();
select public.job_assign_delivery()

select * from delivery_dispatch;

--select init_delivery_detail('WREN-RQGI-32', '447448440754');
select public.manage_delivery_detail();

select * from delivery_dispatch order by dtts desc;

delete from rider_master where rider_name='Syama';
select * from rider_master ;

INSERT INTO rider_master (rider_id, rider_name, vehicle_type, town, status)
VALUES ('447446933210', 'Rahul', 'car', 'Basingstoke', 'active');

select * from delivery_dispatch order by dtts desc;  where rider_id='447448440754';

select * from delivery_option order by id desc;

-- status update to timedout

select count(distinct vehicle_type) 
from delivery_detail where status!='timedout';

update delivery_detail set status='vehicle_type_timedout' where order_number='WREN-QVNU-42';
select status,* from delivery_detail order by dtts desc;
select status,* from delivery_dispatch order by dtts desc;

select * from delivery_inflight di ; 

SELECT public.job_assign_delivery();



    WITH acceptedDispatches AS (
        SELECT 
            * ,
            rank() OVER(PARTITION BY order_number ORDER BY dispatch_id ASC) AS dispatch_rank
        FROM delivery_dispatch dispatch
        WHERE status = 'accepted' AND order_number = 'WREN-QVNU-42'
        AND NOT EXISTS (
            SELECT 1 FROM delivery_inflight WHERE rider_id = dispatch.rider_id
        )
    ), acceptedDispatch AS (
        SELECT distinct
            d.dispatch_id, 
            d.order_number, 
            d.rider_id,
            dd.customer_id  
        FROM acceptedDispatches d
        JOIN delivery_detail dd ON d.order_number = dd.order_number
        WHERE d.dispatch_rank = 1
    )
    select * from acceptedDispatch;


