with unassignedOrders AS (
    SELECT 
        order_number
    FROM delivery_detail
    WHERE status='unassigned'
), firstMsgForunassignedOrders







WITH accepted_msgs AS (
  SELECT 
  *,
  message::JSONB ->> 'order_number' as order_number,
  message::JSONB ->> 'dispatch_id' as dispatch_id,
  message::JSONB ->> 'status' as status,
  message::JSONB ->> 'rider_id' as rider_id,
  RANK() OVER ( PARTITION BY message::JSONB ->> 'order_number' ORDER BY enqueued_at ASC) as msg_rank
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
	UPDATE delivery_dispatch dispatch
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
select * from otherMsg;