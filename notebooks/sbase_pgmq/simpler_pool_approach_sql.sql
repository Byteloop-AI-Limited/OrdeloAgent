with acceptedDispatches as (
	select 
		* ,
		rank() over(partition by order_number order by dispatch_id asc) as dispatch_rank
	from delivery_dispatch dispatch
	where status='accepted' AND order_number=p_order_number
	and not exists (
		select 1 from delivery_inflight where rider_id=dispatch.rider_id
	)
), acceptedDispatch as (
	select 
		d.dispatch_id, 
		d.order_number, 
		d.rider_id,
		dd.customer_id  
	from acceptedDispatches d
	join delivery_detail dd on d.order_number = dd.order_number
	where d.dispatch_rank=1
), updateDispatch as (
	UPDATE delivery_dispatch 
    SET status = 'assigned', 
        status_update_dtts = CURRENT_TIMESTAMP
    WHERE dispatch_id = acceptedDispatch.dispatch_id
), updateDetail as (
	UPDATE delivery_detail 
    SET status = 'assigned', 
        dispatch_id = acceptedDispatch.dispatch_id, 
        rider_id = acceptedDispatch.rider_id
    WHERE order_number = acceptedDispatch.order_number
), insertInflight as (
	INSERT INTO delivery_inflight (
	dispatch_id, order_number, rider_id, customer_id
	)
    VALUES (
	 acceptedDispatch.dispatch_id, 
	 acceptedDispatch.order_number, 
	 acceptedDispatch.rider_id, 
	 acceptedDispatch.customer_id  
	)
)
select * from acceptedDispatch