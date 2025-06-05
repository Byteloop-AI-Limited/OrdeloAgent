-- Veru
select status, dispatch_id, rider_id, order_number from delivery_detail 
--where order_number='0f9d9e9b75fa4db7a1e34e0c53c6b986';
where order_number in ('0f9d9e9b75fa4db7a1e34e0c53c6b986', '8bac3a27f6354abcb3466269a719e13a') 
order by dtts desc;

select * from delivery_inflight
where order_number in ('0f9d9e9b75fa4db7a1e34e0c53c6b986', '8bac3a27f6354abcb3466269a719e13a');

-- setup for testing
update delivery_detail  
set status='unassigned', dispatch_id = null, rider_id = null
--where order_number='0f9d9e9b75fa4db7a1e34e0c53c6b986';
where order_number in ('0f9d9e9b75fa4db7a1e34e0c53c6b986', '8bac3a27f6354abcb3466269a719e13a');

delete from delivery_inflight
where order_number in ('0f9d9e9b75fa4db7a1e34e0c53c6b986', '8bac3a27f6354abcb3466269a719e13a');;

select * from delivery_dispatch;


WITH accepted_msgs AS (
  SELECT 
  *,
  message::JSONB ->> 'order_number' as order_number,
  message::JSONB ->> 'dispatch_id' as dispatch_id,
  message::JSONB ->> 'status' as status,
  message::JSONB ->> 'rider_id' as rider_id,
  RANK() OVER (PARTITION BY message::JSONB ->> 'order_number' ORDER BY enqueued_at ASC) as msg_rank
  FROM pgmq.read(
    queue_name => 'rider_accept_q', vt =>0, qty => 100
  )
  order by enqueued_at desc
), firstMsg AS
(
	select * 
	from accepted_msgs 
	where msg_rank=1 
	and not exists (select 1 from delivery_inflight where rider_id=accepted_msgs.rider_id)
), otherMsg AS
(
	select * 
	from accepted_msgs 
	where msg_rank!=1 
), detailUpdate as (
	update delivery_detail detail 
	set 
	dispatch_id = cast(firstMsg.dispatch_id as INT), 
	status='assigned',
	rider_id=firstMsg.rider_id
	from firstMsg
	where firstMsg.order_number = detail.order_number
	and detail.status='unassigned'
	RETURNING true as updated, firstMsg.dispatch_id, firstMsg.order_number, firstMsg.rider_id, detail.customer_id
), dispatchUpdate as (
	update delivery_dispatch dispatch
	set status_update_dtts=current_timestamp 
	from detailUpdate
	where dispatch.dispatch_id = cast(detailUpdate.dispatch_id as INT)
	and detailUpdate.updated = true
), inflightInsert as (
    INSERT INTO delivery_inflight (dispatch_id, order_number, rider_id, customer_id)
    SELECT 
        cast(dispatch_id as INT),
        order_number,
        rider_id,
        customer_id
    FROM detailUpdate
    WHERE updated = true
)
--select EXISTS (select 1 from detailUpdate) as update_occurred;
select * from otherMsg;